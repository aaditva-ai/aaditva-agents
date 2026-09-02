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
from typing import Any

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
DRAIN_RETRY_BACKOFF_SECONDS = float(os.environ.get("CAMPAIGN_DRIVER_RETRY_BACKOFF_SECONDS", "10"))
CONTINUATION_PROMPT = (
    "Continue the campaign from where you left off. Do not repeat "
    "any specialist calls that already returned a result above -- "
    "pick up with the next step."
)

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


def _get_event_attr(obj: Any, attr: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _is_campaign_terminal(events: list) -> bool:
    """Inspects session events to determine if the campaign reached terminal completion.

    Checks for:
    1. project_manager function_call or function_response (Step 5 execution).
    2. Notion status, project timeline, or deliverables checklist in text or responses.
    3. Final campaign presentation or completion text from the orchestrator.
    """
    if not events:
        return False

    terminal_keywords = (
        "project timeline",
        "notion status",
        "deliverables checklist",
        "campaign presentation",
        "project manager complete",
        "all deliverables complete",
        "phase 1: strategy",
        "phase 1: research",
        "phase 1:",
    )

    for event in reversed(events):
        content = _get_event_attr(event, "content")
        parts = _get_event_attr(content, "parts") or []
        for part in parts:
            fn_call = _get_event_attr(part, "function_call")
            if fn_call is not None:
                name = str(_get_event_attr(fn_call, "name") or "")
                if name == "project_manager" or name.startswith("API-"):
                    return True

            fn_resp = _get_event_attr(part, "function_response")
            if fn_resp is not None:
                name = str(_get_event_attr(fn_resp, "name") or "")
                if name == "project_manager":
                    return True
                resp = _get_event_attr(fn_resp, "response")
                resp_str = str(resp or "").lower()
                if any(kw in resp_str for kw in terminal_keywords):
                    return True

            text = _get_event_attr(part, "text")
            if text and isinstance(text, str):
                text_lower = text.lower()
                if any(kw in text_lower for kw in terminal_keywords):
                    return True

        actions = _get_event_attr(event, "actions")
        if actions:
            actions_str = str(actions).lower()
            if "project_manager" in actions_str:
                return True

    return False


async def _get_session_events(client, session_name: str) -> list:
    return list(client.agent_engines.sessions.events.list(name=session_name))


async def _session_event_count(client, session_name: str) -> int:
    events = await _get_session_events(client, session_name)
    return len(events)


async def _drain(client, agent_engine, session_name: str, user_id: str, session_id: str, message: str) -> int:
    """Drain `async_stream_query` to completion, verifying terminal state.

    On stream completion or mid-stream disconnection/error, inspects durable
    session events for terminal markers (Project Manager output / final presentation).
    If not yet terminal, re-invokes `async_stream_query` with a continuation prompt
    up to `MAX_DRAIN_RETRIES` to guarantee that all planned specialist stages execute.
    Returns the total durable event count.
    """
    attempt = 0
    next_message = message
    last_error: Exception | None = None

    while attempt <= MAX_DRAIN_RETRIES:
        stream_chunks = 0
        try:
            async for _event in agent_engine.async_stream_query(
                user_id=user_id, session_id=session_id, message=next_message
            ):
                stream_chunks += 1

            # Stream finished without raising. Verify if campaign reached terminal state.
            events = await _get_session_events(client, session_name)
            is_terminal = _is_campaign_terminal(events)
            total_events = len(events)
            logger.info(
                "Stream turn finished for session %s (attempt %d/%d, stream_chunks=%d, total_events=%d, terminal=%s)",
                session_id, attempt, MAX_DRAIN_RETRIES, stream_chunks, total_events, is_terminal,
            )

            if is_terminal:
                return total_events

            attempt += 1
            if attempt > MAX_DRAIN_RETRIES:
                logger.warning(
                    "Session %s completed stream turn but did not reach terminal state after %d attempts (%d events).",
                    session_id, attempt - 1, total_events,
                )
                return total_events

            logger.info(
                "Session %s stream turn ended before terminal state (%d events); waiting %.1fs and sending continuation prompt.",
                session_id, total_events, DRAIN_RETRY_BACKOFF_SECONDS,
            )
            await asyncio.sleep(DRAIN_RETRY_BACKOFF_SECONDS)
            next_message = CONTINUATION_PROMPT

        except Exception as e:  # noqa: BLE001
            last_error = e
            attempt += 1
            logger.warning(
                "async_stream_query raised on session %s (attempt %d/%d): %s",
                session_id, attempt, MAX_DRAIN_RETRIES, e,
            )

            # Check server-side session events
            try:
                events = await _get_session_events(client, session_name)
                total_events = len(events)
                is_terminal = _is_campaign_terminal(events)
            except Exception as read_err:
                logger.warning("Failed to read session events for %s after stream error: %s", session_id, read_err)
                events = []
                total_events = 0
                is_terminal = False

            if is_terminal:
                logger.info(
                    "Session %s reached terminal state server-side despite stream error (%d events); concluding drive.",
                    session_id, total_events,
                )
                return total_events

            if attempt > MAX_DRAIN_RETRIES:
                logger.error(
                    "Session %s exhausted retries (%d/%d) without reaching terminal state (%d events).",
                    session_id, attempt, MAX_DRAIN_RETRIES, total_events,
                )
                break

            logger.info(
                "Session %s not yet terminal (%d events); waiting %.1fs before retry with continuation prompt.",
                session_id, total_events, DRAIN_RETRY_BACKOFF_SECONDS,
            )
            await asyncio.sleep(DRAIN_RETRY_BACKOFF_SECONDS)
            next_message = CONTINUATION_PROMPT

    raise last_error or RuntimeError(f"Drain failed for session {session_id} without reaching terminal state")


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
