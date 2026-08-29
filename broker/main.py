"""broker: the three short, authenticated routes the SPA talks to.

POST /campaigns                          - start a campaign, returns in ~1s
GET  /campaigns                          - list the caller's campaigns
GET  /campaigns/{sessionId}/events       - poll the transcript

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
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import auth
import campaign_limits
import campaign_queue
import campaign_store
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


def _require_uid(request: Request) -> str:
    """Raises auth.AuthError (caught by each handler) if verification fails."""
    return auth.verify_id_token(request.headers.get("Authorization", ""))


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
        uid = _require_uid(request)
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
        admission = await campaign_limits.check_admission(uid)
    except RuntimeError as e:
        logger.exception("Rate limiter unavailable")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=503)

    if not admission["allowed"]:
        return JSONResponse(
            {"status": "error", "error": admission["error"]}, status_code=429
        )

    session_id = str(uuid.uuid4())
    await campaign_store.create_dispatched(session_id, uid, prompt)
    await campaign_queue.enqueue(session_id, uid, prompt)

    logger.info("Campaign %s dispatched for user %s", session_id, uid)
    return JSONResponse({"sessionId": session_id})


async def handle_list_campaigns(request: Request) -> JSONResponse:
    try:
        uid = _require_uid(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    docs = await campaign_store.list_campaigns_for_user(uid)
    campaigns = [
        {
            "sessionId": doc.get("session_id"),
            "title": (doc.get("prompt") or "")[:TITLE_MAX_CHARS],
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


async def handle_get_events(request: Request) -> JSONResponse:
    try:
        uid = _require_uid(request)
    except auth.AuthError as e:
        return JSONResponse({"error": "unauthorized", "detail": str(e)}, status_code=401)

    session_id = request.path_params["session_id"]
    since = request.query_params.get("since")

    campaign_doc = await campaign_store.get_campaign(session_id)
    if campaign_doc is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if campaign_doc.get("user_id") != uid:
        # Same response as "not found" -- do not confirm a session exists
        # to a caller who does not own it.
        return JSONResponse({"error": "not found"}, status_code=404)

    events = sessions_client.list_events(session_id, since=since)
    steps = dedupe_by_id(normalize_events(events))

    # `since` filters the query but does not bound how fresh the campaign
    # is overall, so the cursor returned here -- and the staleness check
    # below -- must be based on the latest event actually seen in this
    # response, not merely "did this page have anything new."
    latest_timestamp = max((s["timestamp"] for s in steps if s.get("timestamp")), default=None)
    next_cursor = latest_timestamp or since

    # Staleness must be judged against the true last-event time, not just
    # this page's delta -- a poll can legitimately return zero new steps
    # while the campaign is still healthy and simply between specialist
    # calls (Step 1 observed multi-minute gaps between calls). The broker
    # is stateless across polls, so when this page has no new steps the
    # best available proxy for "when did something last happen" is the
    # cursor the client already knows about (`since`, which -- per the
    # polling contract -- is the previous response's own cursor, i.e. the
    # last event timestamp this session had as of the prior poll). Only
    # when there is no `since` at all (the very first poll, before any
    # event exists) does this fall back to the campaign document's
    # updated_at, so a fresh "dispatched" campaign isn't flagged stalled
    # before campaign-driver has even started.
    if latest_timestamp:
        freshness_source = latest_timestamp
    elif since:
        freshness_source = since
    else:
        freshness_source = None

    if freshness_source:
        latest_dt = datetime.datetime.fromisoformat(freshness_source.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
    else:
        latest_dt = campaign_doc.get("updated_at")
        now = datetime.datetime.now(latest_dt.tzinfo) if latest_dt else None

    is_recent = True
    if latest_dt is not None and now is not None:
        is_recent = (now - latest_dt).total_seconds() < STALL_THRESHOLD_SECONDS

    status = _derive_status(campaign_doc, is_recent)

    return JSONResponse({
        "cursor": next_cursor,
        "status": status,
        "steps": steps,
    })


async def handle_health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = Starlette(
    routes=[
        Route("/campaigns", handle_create_campaign, methods=["POST"]),
        Route("/campaigns", handle_list_campaigns, methods=["GET"]),
        Route("/campaigns/{session_id}/events", handle_get_events, methods=["GET"]),
        Route("/healthz", handle_health, methods=["GET"]),
    ]
)


if __name__ == "__main__":
    import uvicorn

    PORT = int(os.getenv("PORT", "8080"))
    HOST = os.getenv("HOST", "0.0.0.0")
    logger.info(f"Starting broker on {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
