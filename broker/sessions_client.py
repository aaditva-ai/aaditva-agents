"""Thin wrapper around the Agent Engine session store for the broker's
events route.

Same `vertexai.Client` connection pattern as scripts/spikes/common.py and
campaign-driver/main.py (plan Key Decision #9: the non-deprecated client
path, no `stream_query`/`create_session` etc.).
"""
import os

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
LOCATION = (
    os.environ.get("CLOUD_RUN_REGION")
    or os.environ.get("GCP_REGION")
    or os.environ.get("LOCATION", "us-central1")
)
AGENT_ENGINE_ID = os.environ.get("AGENT_ENGINE_ID")

_client = None


def _agent_engine_resource_name() -> str:
    if AGENT_ENGINE_ID and AGENT_ENGINE_ID.startswith("projects/"):
        return AGENT_ENGINE_ID
    return f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{AGENT_ENGINE_ID}"


def _get_client():
    global _client
    if _client is None:
        import vertexai
        from vertexai import Client

        vertexai.init(project=PROJECT_ID, location=LOCATION)
        _client = Client(project=PROJECT_ID, location=LOCATION)
    return _client


def session_name(session_id: str) -> str:
    return f"{_agent_engine_resource_name()}/sessions/{session_id}"


def list_events(session_id: str, since: str | None = None) -> list:
    """Calls sessions.events.list, optionally filtered to timestamp >=
    `since` (an RFC3339 string). Mirrors scripts/spikes/common.py's
    list_events, the exact call Step 1 confirmed surfaces events
    mid-invocation.

    Treats a 404 from the Agent Engine session store as "no events yet"
    rather than letting it propagate: there's an inherent race between the
    broker enqueueing the Cloud Tasks dispatch (POST /campaigns returns
    immediately, per the plan's ~1s requirement) and campaign-driver
    actually connecting and creating the session server-side -- the SPA's
    very first poll can genuinely land before the session exists.
    campaign_doc's own status ("dispatched") already tells the caller
    correctly that nothing has started yet; a 404 here should read the
    same way, not surface as an unhandled 500. Caught live: this was an
    unhandled exception in handle_get_events, which produced a 500 with no
    CORS header attached (the exception escapes before Starlette's CORS
    middleware can write it), which browsers report as a misleading "CORS
    policy" error rather than the real 500.
    """
    from google.genai import errors as genai_errors

    client = _get_client()
    config = {"filter": f'timestamp>="{since}"'} if since else None
    try:
        return list(
            client.agent_engines.sessions.events.list(name=session_name(session_id), config=config)
        )
    except genai_errors.APIError as e:
        if e.code == 404:
            return []
        raise
