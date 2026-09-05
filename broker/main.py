"""broker: the short, authenticated routes the SPA talks to.

POST /campaigns                          - start a campaign, returns in ~1s
GET  /campaigns                          - list the caller's campaigns
GET  /campaigns/{sessionId}/events       - poll the transcript
POST /campaigns/{sessionId}/resume       - Step 6: re-drive a failed/stalled campaign

No route here ever holds a long-lived connection or drives a campaign
itself -- that is entirely campaign-driver's job via the Cloud Tasks queue
(plan Non-Functional Requirements: "No broker HTTP request exceeds ~1s").
"""
import datetime
import logging
import os
import uuid

from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import auth
import campaign_limits
import campaign_queue
import campaign_store
import eval_service
import judge_service
import sessions_client
from events_normalizer import dedupe_by_id, normalize_events

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("broker.main")

# How long (seconds) a `running` campaign may go without a new event before
# the events route reports "stalled" instead of "running" -- inferred
# purely from event staleness since a genuinely killed container never gets
# a chance to write a `failed` status itself (see the Decisions section in
# docs/replace-gradio-with-spa-job-architecture.md for the reasoning and
# the observed inter-event gaps this default is based on).
STALL_THRESHOLD_SECONDS = float(os.environ.get("CAMPAIGN_STALL_THRESHOLD_SECONDS", "600"))

TITLE_MAX_CHARS = 80


def _require_user(request: Request) -> auth.AuthenticatedUser:
    """Raises auth.AuthError (caught by each handler) if verification fails."""
    return auth.verify_id_token(request.headers.get("Authorization", ""))


def _utc_now_rfc3339() -> str:
    """Matches scripts/spikes/common.py's utc_now_rfc3339 format, the same
    shape sessions_client.list_events expects for its `since` filter.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _iso(value) -> str | None:
    """Firestore timestamps deserialize as datetime; JSONResponse can't
    serialize those directly, so every doc field that might be one goes
    through this before being placed in a response body.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def handle_create_campaign(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    prompt = (body or {}).get("prompt")
    if not prompt or not isinstance(prompt, str):
        return JSONResponse({"error": "missing prompt"}, status_code=400)

    try:
        admission = await campaign_limits.check_admission(user.uid, is_anonymous=user.is_anonymous)
    except RuntimeError as e:
        logger.exception("Rate limiter unavailable")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=503)

    if not admission["allowed"]:
        return JSONResponse(
            {"status": "error", "error": admission["error"]}, status_code=429
        )

    session_id = str(uuid.uuid4())
    await campaign_store.create_dispatched(session_id, user.uid, prompt)
    await campaign_queue.enqueue(session_id, user.uid, prompt)

    logger.info("Campaign %s dispatched for user %s", session_id, user.uid)
    return JSONResponse({"sessionId": session_id})


async def handle_list_campaigns(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    docs = await campaign_store.list_campaigns_for_user(user.uid)
    campaigns = [
        {
            "sessionId": doc.get("session_id"),
            "title": (doc.get("prompt") or "")[:TITLE_MAX_CHARS],
            "prompt": doc.get("prompt") or "",
            "status": doc.get("status"),
            "createdAt": _iso(doc.get("created_at")),
            "lastEventAt": _iso(doc.get("updated_at")),
        }
        for doc in docs
    ]
    return JSONResponse({"campaigns": campaigns})


def _derive_status(campaign_doc: dict | None, is_recent: bool) -> str:
    """Combine the Firestore campaign document with event-staleness to
    distinguish crash (doc says `failed`) from stall (doc still says
    `running`/`dispatched` but nothing new has landed) -- plan Key Decision
    #5 / Functional Requirement 5.
    """
    if campaign_doc is None:
        return "failed"

    doc_status = campaign_doc.get("status")
    if doc_status in ("complete", "failed"):
        return doc_status

    # "dispatched" or "running": both can silently stall (task never picked
    # up, or the container died without a chance to write `failed`).
    # `doc_status` itself -- not whether *this poll's page* saw a new step
    # -- distinguishes "never started" from "in progress": campaign-driver
    # transitions dispatched -> running (main.py's mark_running) before it
    # streams a single event, so by the time any event exists the document
    # already reads "running". Using latest_step_timestamp's presence
    # instead would mislabel a healthy running campaign as "starting"
    # whenever a poll simply had no new steps between specialist calls.
    if not is_recent:
        return "stalled"
    return "starting" if doc_status == "dispatched" else "running"


def _is_recent(freshness_source: str | None, campaign_doc: dict) -> bool:
    """True if `freshness_source` (an RFC3339 timestamp) -- or, absent one,
    the campaign document's own `updated_at` -- is within
    STALL_THRESHOLD_SECONDS of now.
    """
    if freshness_source:
        latest_dt = datetime.datetime.fromisoformat(freshness_source.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
    else:
        latest_dt = campaign_doc.get("updated_at")
        now = datetime.datetime.now(latest_dt.tzinfo) if latest_dt else None

    if latest_dt is None or now is None:
        return True
    return (now - latest_dt).total_seconds() < STALL_THRESHOLD_SECONDS


def _fetch_steps_and_status(campaign_doc: dict, session_id: str, since: str | None) -> tuple[list[dict], str | None, str]:
    """Shared by handle_get_events and handle_resume_campaign: reads
    session events since `since`, dedupes/normalizes them, and derives the
    combined doc+staleness status (plan Key Decision #5). Returns
    (steps, next_cursor, status).
    """
    events = sessions_client.list_events(session_id, since=since)
    steps = dedupe_by_id(normalize_events(events))

    # `since` filters the query but does not bound how fresh the campaign
    # is overall, so the cursor returned here -- and the staleness check
    # below -- must be based on the latest event actually seen in this
    # response, not merely "did this page have anything new."
    latest_timestamp = max((s["timestamp"] for s in steps if s.get("timestamp")), default=None)
    # `cursor` must never be null once a campaign has been dispatched: the
    # SPA advances its poll by calling useInfiniteQuery's fetchNextPage(),
    # whose underlying fetch is skipped entirely when the *page param*
    # (this cursor) is null and at least one page has already been fetched
    # (see @tanstack/query-core's infiniteQueryBehavior.ts) -- a null
    # cursor would silently and permanently stop polling the very first
    # time a "dispatched" campaign is polled before it has any events yet.
    # Falling back to "now" gives the next poll a valid (if narrow) filter
    # that still correctly picks up whatever arrives after this instant.
    next_cursor = latest_timestamp or since or _utc_now_rfc3339()

    # Staleness must be judged against the true last-event time, not just
    # this page's delta -- a poll can legitimately return zero new steps
    # while the campaign is still healthy and simply between specialist
    # calls (Step 1 observed multi-minute gaps between calls). When this
    # page has no new steps, the best available proxy for "when did
    # something last happen" is the cursor the caller already knows about
    # (`since`, which -- per the polling contract -- is the previous
    # response's own cursor). Only when there is no `since` at all (the
    # very first poll, before any event exists) does this fall back to the
    # campaign document's updated_at, so a fresh "dispatched" campaign
    # isn't flagged stalled before campaign-driver has even started.
    freshness_source = latest_timestamp or since
    status = _derive_status(campaign_doc, _is_recent(freshness_source, campaign_doc))

    return steps, next_cursor, status


async def handle_get_events(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    session_id = request.path_params["session_id"]
    since = request.query_params.get("since")

    campaign_doc = await campaign_store.get_campaign(session_id)
    if campaign_doc is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if campaign_doc.get("user_id") != user.uid:
        # Same response as "not found" -- do not confirm a session exists
        # to a caller who does not own it.
        return JSONResponse({"error": "not found"}, status_code=404)

    steps, next_cursor, status = _fetch_steps_and_status(campaign_doc, session_id, since)

    return JSONResponse({
        "cursor": next_cursor,
        "status": status,
        "steps": steps,
    })


async def handle_resume_campaign(request: Request) -> JSONResponse:
    """POST /campaigns/{sessionId}/resume -- re-enqueues a drive task on an
    existing session (plan Step 6's useResumeCampaign). Subject to the same
    per-user admission checks as starting a new campaign, since a resume is
    still a real drive that consumes the same quota.

    Deliberately does NOT call campaign_store.create_dispatched: that would
    reset `created_at`/overwrite `prompt`. Whether a resume is allowed is
    checked against the *derived* status (the same _derive_status
    handle_get_events uses), not the raw Firestore doc status: a genuinely
    stalled campaign-driver crash never gets a chance to write `failed` --
    the document is left reading `running` forever, exactly the case
    Functional Requirement 5 exists to handle. Checking the raw doc status
    here instead would make a real stall permanently unresumable. Only the
    derived `running` (truly still in progress -- fresh events) and
    `complete` block a resume; `failed` and `stalled` are exactly what this
    route exists for.
    """
    try:
        user = _require_user(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    session_id = request.path_params["session_id"]
    campaign_doc = await campaign_store.get_campaign(session_id)
    if campaign_doc is None or campaign_doc.get("user_id") != user.uid:
        return JSONResponse({"error": "not found"}, status_code=404)

    _, _, derived_status = _fetch_steps_and_status(campaign_doc, session_id, since=None)
    if derived_status in ("running", "complete"):
        return JSONResponse(
            {"status": "error", "error": f"cannot resume a campaign that is already {derived_status}"},
            status_code=409,
        )

    try:
        admission = await campaign_limits.check_admission(user.uid, is_anonymous=user.is_anonymous)
    except RuntimeError as e:
        logger.exception("Rate limiter unavailable")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=503)

    if not admission["allowed"]:
        return JSONResponse({"status": "error", "error": admission["error"]}, status_code=429)

    prompt = (
        "Continue the campaign from where you left off. Do not repeat any "
        "specialist calls that already returned a result above -- pick up "
        "with the next step."
    )
    await campaign_queue.enqueue(session_id, user.uid, prompt)

    logger.info("Campaign %s resumed for user %s", session_id, user.uid)
    return JSONResponse({"status": "ok", "sessionId": session_id})


async def handle_eval_health(request: Request) -> JSONResponse:
    try:
        report = await eval_service.check_all_health()
        return JSONResponse(report)
    except Exception as e:
        logger.exception("Error during eval health check")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


async def handle_eval_benchmarks(request: Request) -> JSONResponse:
    return JSONResponse({"benchmarks": eval_service.get_benchmark_briefs()})


async def handle_eval_prepare_quotas(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
        if user and user.uid:
            await campaign_limits.elevate_user_allowance(user.uid, max_concurrent=10, tokens=20)
    except Exception as e:
        logger.info("Elevating quotas without user auth: %s", e)

    try:
        result = await eval_service.prepare_parallel_image_quotas()
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Error during eval prepare quotas")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


async def handle_trigger_judge(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    session_id = (body or {}).get("sessionId")
    if not session_id or not isinstance(session_id, str):
        return JSONResponse({"error": "missing sessionId"}, status_code=400)

    campaign_doc = await campaign_store.get_campaign(session_id)
    if campaign_doc is None or campaign_doc.get("user_id") != user.uid:
        return JSONResponse({"error": "not found"}, status_code=404)

    # Check cached evaluation first to minimize AI spend and unnecessary LLM tokens
    force_reeval = bool((body or {}).get("force", False))
    if not force_reeval:
        cached = await judge_service.get_cached_evaluation(session_id)
        if cached:
            return JSONResponse(cached)

    steps, _, derived_status = _fetch_steps_and_status(campaign_doc, session_id, since=None)
    prompt = campaign_doc.get("prompt", "")

    evaluation = await judge_service.evaluate_campaign_transcript(session_id, prompt, steps)
    return JSONResponse(evaluation)


async def handle_get_campaign_eval(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    session_id = request.path_params["session_id"]
    campaign_doc = await campaign_store.get_campaign(session_id)
    if campaign_doc is None or campaign_doc.get("user_id") != user.uid:
        return JSONResponse({"error": "not found"}, status_code=404)

    cached = await judge_service.get_cached_evaluation(session_id)
    if cached:
        return JSONResponse(cached)

    return JSONResponse({"sessionId": session_id, "evaluated": False})


async def handle_get_average_eval(request: Request) -> JSONResponse:
    """GET /evals/average -- the aggregate rubric scorecard shown above the
    per-brief runs section (Evaluation Dashboard): averages every cached
    LLM Judge evaluation across all of the signed-in caller's campaign
    runs, not just one session at a time.
    """
    try:
        user = _require_user(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    report = await judge_service.compute_user_average_evaluation(user.uid)
    return JSONResponse(report)


async def handle_health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# The SPA calls the broker's absolute Cloud Run URL directly (VITE_BROKER_URL)
# rather than through a same-origin Firebase Hosting rewrite -- the broker's
# routes were built and validated live at /campaigns, not /api/campaigns, so
# CORS here is the path that needed no re-verification of already-deployed
# routes. Firebase Hosting rewrites remain available for a same-origin setup
# later; this is the pragmatic choice for what's actually deployed today
# (see the Decisions section for Step 4 in
# docs/replace-gradio-with-spa-job-architecture.md).
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("BROKER_ALLOWED_ORIGINS", "").split(",") if o.strip()]

app = Starlette(
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=ALLOWED_ORIGINS,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        ),
    ],
    routes=[
        Route("/campaigns", handle_create_campaign, methods=["POST"]),
        Route("/campaigns", handle_list_campaigns, methods=["GET"]),
        Route("/campaigns/{session_id}/events", handle_get_events, methods=["GET"]),
        Route("/campaigns/{session_id}/resume", handle_resume_campaign, methods=["POST"]),
        Route("/evals/health", handle_eval_health, methods=["GET"]),
        Route("/evals/benchmarks", handle_eval_benchmarks, methods=["GET"]),
        Route("/evals/prepare-quotas", handle_eval_prepare_quotas, methods=["POST"]),
        Route("/evals/judge", handle_trigger_judge, methods=["POST"]),
        Route("/evals/campaigns/{session_id}", handle_get_campaign_eval, methods=["GET"]),
        Route("/evals/average", handle_get_average_eval, methods=["GET"]),
        Route("/healthz", handle_health, methods=["GET"]),
    ]
)


if __name__ == "__main__":
    import uvicorn

    PORT = int(os.getenv("PORT", "8080"))
    HOST = os.getenv("HOST", "0.0.0.0")
    logger.info(f"Starting broker on {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
