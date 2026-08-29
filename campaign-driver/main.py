"""campaign-driver: the Cloud Tasks push target that drives one campaign to
completion with no client attached.

Runs on its own Cloud Run service (never the broker's) so a broker redeploy
can never kill an in-flight campaign, per Key Decision #2 in
docs/replace-gradio-with-spa-job-architecture.md. Accepts only
OIDC-authenticated Cloud Tasks pushes -- see _verify_cloud_tasks_oidc_token,
which mirrors agents/designer/task_handler.py's verification.

Step 1 spikes (scripts/spikes/README.md) found that a live campaign
repeatedly hit a transient `503 UNAVAILABLE` from async_stream_query around
the 9-10 minute mark, and that in every case the session kept executing and
even reached full completion on the server with no client attached. _drain
below treats a mid-stream error as "go check whether the session actually
finished" rather than an immediate failure, consistent with that finding.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import campaign_store

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("campaign_driver.main")

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
LOCATION = (
    os.environ.get("CLOUD_RUN_REGION")
    or os.environ.get("GCP_REGION")
    or os.environ.get("LOCATION", "us-central1")
)
AGENT_ENGINE_ID = os.environ.get("AGENT_ENGINE_ID")

CAMPAIGN_TASKS_INVOKER_SA = os.environ.get("CAMPAIGN_TASKS_INVOKER_SA")
CAMPAIGN_TASK_HANDLER_URL = os.environ.get("CAMPAIGN_TASK_HANDLER_URL")

# How many times _drain will re-attempt async_stream_query after a
# mid-stream backend error before giving up. Each retry first re-reads the
# session to check whether the backend actually finished despite the client
# error (see the module docstring) -- this bounds retries for the case where
# it genuinely has not.
MAX_DRAIN_RETRIES = int(os.environ.get("CAMPAIGN_DRIVER_MAX_DRAIN_RETRIES", "3"))
DRAIN_RETRY_BACKOFF_SECONDS = float(os.environ.get("CAMPAIGN_DRIVER_RETRY_BACKOFF_SECONDS", "5"))

_auth_request = google_auth_requests.Request()
_client = None
_agent_engine = None


def _agent_engine_resource_name() -> str:
    if AGENT_ENGINE_ID and AGENT_ENGINE_ID.startswith("projects/"):
        return AGENT_ENGINE_ID
    return f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{AGENT_ENGINE_ID}"


def _get_agent_engine():
    """Lazily construct the module-level vertexai.Client + AgentEngine handle.

    Uses the non-deprecated `vertexai.Client` path (plan Key Decision #9),
    same connection pattern as scripts/spikes/common.py and run_campaign.py.
    """
    global _client, _agent_engine
    if _agent_engine is None:
        import vertexai
        from vertexai import Client

        vertexai.init(project=PROJECT_ID, location=LOCATION)
        _client = Client(project=PROJECT_ID, location=LOCATION)
        _agent_engine = _client.agent_engines.get(name=_agent_engine_resource_name())
    return _client, _agent_engine


def _verify_cloud_tasks_oidc_token(authorization_header: str) -> bool:
    """Verify the `Authorization: Bearer <OIDC token>` header Cloud Tasks
    attaches to its push requests, checking both audience and invoker
    identity. Mirrors agents/designer/task_handler.py.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return False

    token = authorization_header.removeprefix("Bearer ").strip()
    try:
        claims = id_token.verify_oauth2_token(
            token, _auth_request, audience=CAMPAIGN_TASK_HANDLER_URL
        )
    except Exception:
        logger.exception("Failed to verify Cloud Tasks OIDC token")
        return False

    return claims.get("email") == CAMPAIGN_TASKS_INVOKER_SA


async def _session_event_count(client, session_name: str) -> int:
    events = list(client.agent_engines.sessions.events.list(name=session_name))
    return len(events)


async def _drain(client, agent_engine, session_name: str, user_id: str, session_id: str, message: str) -> int:
    """Drain `async_stream_query` to completion, never breaking early --
    required for ADK's post-run event compaction to have a chance to run
    (runners.py:515-519; Step 1 found it did not fire on campaigns this
    small, but the drive must still not preclude it for larger ones).

    On a mid-stream error, re-reads the durable session before deciding
    whether to retry: if the backend kept going and the event count is no
    longer growing across a short wait, we treat the drive as complete
    rather than retrying a campaign that already finished server-side (see
    module docstring). Otherwise it retries by re-invoking on the same
    session_id, relying on the same continue-from-history behavior Step 1's
    spike_resume confirmed.
    """
    attempt = 0
    next_message = message
    last_error: Exception | None = None

    while attempt <= MAX_DRAIN_RETRIES:
        event_count = 0
        try:
            async for _event in agent_engine.async_stream_query(
                user_id=user_id, session_id=session_id, message=next_message
            ):
                event_count += 1
            return event_count
        except Exception as e:  # noqa: BLE001 -- deliberately broad: any
            # stream failure (503s observed in Step 1, but not exclusively)
            # should fall through to the same server-truth check below.
            last_error = e
            attempt += 1
            logger.warning(
                "async_stream_query raised on session %s (attempt %d/%d): %s",
                session_id, attempt, MAX_DRAIN_RETRIES, e,
            )
            if attempt > MAX_DRAIN_RETRIES:
                break

            await asyncio.sleep(DRAIN_RETRY_BACKOFF_SECONDS)
            count_before = await _session_event_count(client, session_name)
            await asyncio.sleep(DRAIN_RETRY_BACKOFF_SECONDS)
            count_after = await _session_event_count(client, session_name)
            if count_after == count_before and count_after > 0:
                logger.info(
                    "Session %s event count stable at %d after stream error; "
                    "treating campaign as complete server-side rather than retrying.",
                    session_id, count_after,
                )
                return count_after

            logger.info(
                "Session %s still growing (%d -> %d) after stream error; "
                "re-invoking to continue the drive.",
                session_id, count_before, count_after,
            )
            next_message = (
                "Continue the campaign from where you left off. Do not repeat "
                "any specialist calls that already returned a result above -- "
                "pick up with the next step."
            )

    raise last_error or RuntimeError(f"Drain failed for session {session_id} with no captured error")


async def handle_drive(request: Request) -> JSONResponse:
    """POST /drive -- the Cloud Tasks push target. Body: {sessionId, userId, prompt}."""
    if not _verify_cloud_tasks_oidc_token(request.headers.get("Authorization", "")):
        logger.warning("Rejected /drive request with invalid/missing OIDC token")
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    session_id = payload.get("sessionId")
    user_id = payload.get("userId")
    prompt = payload.get("prompt")
    if not session_id or not user_id or not prompt:
        return JSONResponse({"error": "missing sessionId, userId, or prompt"}, status_code=400)

    acquired = await campaign_store.mark_running(session_id)
    if not acquired:
        logger.info("Campaign %s already running or terminal; refusing re-entry.", session_id)
        return JSONResponse({"status": "skipped", "reason": "already running or terminal"})

    client, agent_engine = _get_agent_engine()
    session_name = f"{_agent_engine_resource_name()}/sessions/{session_id}"

    try:
        event_count = await _drain(client, agent_engine, session_name, user_id, session_id, prompt)
    except Exception as e:
        logger.exception("Campaign %s failed", session_id)
        await campaign_store.mark_failed(session_id, str(e))
        # 5xx tells Cloud Tasks the push failed, but the queue is configured
        # --max-attempts=1 (deploy_campaign_driver.py) so this never causes
        # a silent duplicate dispatch -- it only surfaces in Cloud Run logs
        # and the campaign document's `failed` status.
        return JSONResponse({"status": "error", "sessionId": session_id, "error": str(e)}, status_code=500)

    await campaign_store.mark_complete(session_id, event_count)
    logger.info("Campaign %s complete: %d events", session_id, event_count)
    return JSONResponse({"status": "ok", "sessionId": session_id, "eventCount": event_count})


async def handle_health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = Starlette(
    routes=[
        Route("/drive", handle_drive, methods=["POST"]),
        Route("/healthz", handle_health, methods=["GET"]),
    ]
)


if __name__ == "__main__":
    import uvicorn

    PORT = int(os.getenv("PORT", "8080"))
    HOST = os.getenv("HOST", "0.0.0.0")
    logger.info(f"Starting campaign-driver on {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
