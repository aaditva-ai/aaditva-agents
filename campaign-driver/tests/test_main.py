"""Unit tests for campaign-driver's request handling and drain-retry logic.

No live GCP calls: `_get_agent_engine`/OIDC verification/Firestore are all
monkeypatched so these run offline and fast, exercising the actual branching
logic (auth rejection, payload validation, re-entry guard, the
retry-vs-treat-as-complete decision in `_drain`) rather than infra plumbing.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import campaign_store  # noqa: E402
import main  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_oidc(monkeypatch):
    """By default, treat every request as authenticated; individual tests
    override this to exercise the rejection path.
    """
    monkeypatch.setattr(main, "_verify_cloud_tasks_oidc_token", lambda header: True)


def test_drive_rejects_missing_oidc_token(monkeypatch):
    monkeypatch.setattr(main, "_verify_cloud_tasks_oidc_token", lambda header: False)
    client = TestClient(main.app)
    resp = client.post("/drive", json={"sessionId": "s1", "userId": "u1", "prompt": "hi"})
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"userId": "u1", "prompt": "hi"},
        {"sessionId": "s1", "prompt": "hi"},
        {"sessionId": "s1", "userId": "u1"},
        {},
    ],
)
def test_drive_rejects_incomplete_payload(body):
    client = TestClient(main.app)
    resp = client.post("/drive", json=body)
    assert resp.status_code == 400


def test_drive_skips_when_already_running(monkeypatch):
    monkeypatch.setattr(campaign_store, "mark_running", AsyncMock(return_value=False))
    client = TestClient(main.app)
    resp = client.post("/drive", json={"sessionId": "s1", "userId": "u1", "prompt": "hi"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


def test_drive_success_marks_complete(monkeypatch):
    monkeypatch.setattr(campaign_store, "mark_running", AsyncMock(return_value=True))
    mark_complete = AsyncMock()
    monkeypatch.setattr(campaign_store, "mark_complete", mark_complete)
    monkeypatch.setattr(main, "_get_agent_engine", lambda: (object(), object()))
    monkeypatch.setattr(main, "_drain", AsyncMock(return_value=7))

    client = TestClient(main.app)
    resp = client.post("/drive", json={"sessionId": "s1", "userId": "u1", "prompt": "hi"})

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "sessionId": "s1", "eventCount": 7}
    mark_complete.assert_awaited_once_with("s1", 7)


def test_drive_failure_marks_failed_and_returns_500(monkeypatch):
    monkeypatch.setattr(campaign_store, "mark_running", AsyncMock(return_value=True))
    mark_failed = AsyncMock()
    monkeypatch.setattr(campaign_store, "mark_failed", mark_failed)
    monkeypatch.setattr(main, "_get_agent_engine", lambda: (object(), object()))
    monkeypatch.setattr(main, "_drain", AsyncMock(side_effect=RuntimeError("boom")))

    client = TestClient(main.app)
    resp = client.post("/drive", json={"sessionId": "s1", "userId": "u1", "prompt": "hi"})

    assert resp.status_code == 500
    mark_failed.assert_awaited_once()
    assert mark_failed.await_args.args[0] == "s1"


def test_health_ok():
    client = TestClient(main.app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


class _FakeAgentEngine:
    """Simulates async_stream_query: yields chunks and optionally raises errors."""

    def __init__(self, events_before_error: int = 0, raise_error: bool = False, error_on_call: int = 1):
        self.events_before_error = events_before_error
        self.raise_error = raise_error
        self.error_on_call = error_on_call
        self.calls = 0
        self.messages = []

    async def async_stream_query(self, user_id, session_id, message):
        self.calls += 1
        self.messages.append(message)
        for _ in range(self.events_before_error):
            yield {"author": "creative_director"}
        if self.raise_error and self.calls == self.error_on_call:
            raise RuntimeError("503 UNAVAILABLE")


class _FakeSessionsEventsList:
    """Returns predetermined event lists on successive calls."""

    def __init__(self, event_batches: list[list]):
        self._batches = list(event_batches)

    def list(self, name):
        if self._batches:
            return self._batches.pop(0)
        return []


class _FakeClient:
    def __init__(self, event_batches: list[list]):
        self.agent_engines = type("_", (), {})()
        self.agent_engines.sessions = type("_", (), {})()
        self.agent_engines.sessions.events = _FakeSessionsEventsList(event_batches)


def test_is_campaign_terminal():
    assert not main._is_campaign_terminal([])

    non_terminal_events = [
        {"content": {"parts": [{"text": "Starting market research..."}]}},
        {"content": {"parts": [{"function_call": {"name": "brand_strategist"}}]}},
        {"content": {"parts": [{"function_response": {"name": "brand_strategist", "response": {"result": "research"}}}]}},
        {"content": {"parts": [{"function_call": {"name": "copywriter"}}]}},
        {"content": {"parts": [{"function_response": {"name": "copywriter", "response": {"result": "posts"}}}]}},
    ]
    assert not main._is_campaign_terminal(non_terminal_events)

    terminal_pm_call = [
        {"content": {"parts": [{"function_call": {"name": "project_manager"}}]}}
    ]
    assert main._is_campaign_terminal(terminal_pm_call)

    terminal_pm_resp = [
        {"content": {"parts": [{"function_response": {"name": "project_manager", "response": {"result": "Done"}}}]}}
    ]
    assert main._is_campaign_terminal(terminal_pm_resp)

    terminal_timeline_text = [
        {"content": {"parts": [{"text": "**Project Timeline:**\nPhase 1: Strategy\n**Notion Status:** Created 5 tasks"}]}}
    ]
    assert main._is_campaign_terminal(terminal_timeline_text)


@pytest.mark.asyncio
async def test_drain_completes_when_terminal_on_first_stream(monkeypatch):
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(return_value=None))

    agent_engine = _FakeAgentEngine(events_before_error=3, raise_error=False)
    terminal_events = [
        {"content": {"parts": [{"function_response": {"name": "project_manager", "response": {"result": "timeline"}}}]}}
    ] * 10
    client = _FakeClient(event_batches=[terminal_events])

    result = await main._drain(
        client, agent_engine, "session-name", "user-1", "session-1", "Create campaign"
    )
    assert result == 10
    assert agent_engine.calls == 1


@pytest.mark.asyncio
async def test_drain_recovers_when_session_already_terminal_after_error(monkeypatch):
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(return_value=None))

    agent_engine = _FakeAgentEngine(events_before_error=0, raise_error=True, error_on_call=1)
    terminal_events = [
        {"content": {"parts": [{"function_response": {"name": "project_manager", "response": {"result": "timeline"}}}]}}
    ] * 12
    client = _FakeClient(event_batches=[terminal_events])

    result = await main._drain(
        client, agent_engine, "session-name", "user-1", "session-1", "Create campaign"
    )
    assert result == 12
    assert agent_engine.calls == 1  # Terminal verified on server side; no second invocation needed


@pytest.mark.asyncio
async def test_drain_re_invokes_continuation_when_mid_stream_error_and_not_terminal(monkeypatch):
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(return_value=None))

    agent_engine = _FakeAgentEngine(events_before_error=0, raise_error=True, error_on_call=1)
    non_terminal_events = [
        {"content": {"parts": [{"function_response": {"name": "designer", "response": {"result": "images"}}}]}}
    ] * 5
    terminal_events = [
        {"content": {"parts": [{"function_response": {"name": "project_manager", "response": {"result": "timeline"}}}]}}
    ] * 14
    # First call: incomplete events after error; Second call (stream finishes): terminal events
    client = _FakeClient(event_batches=[non_terminal_events, terminal_events])

    result = await main._drain(
        client, agent_engine, "session-name", "user-1", "session-1", "Create campaign"
    )
    assert result == 14
    assert agent_engine.calls == 2
    assert agent_engine.messages[1] == main.CONTINUATION_PROMPT


@pytest.mark.asyncio
async def test_drain_re_invokes_continuation_when_clean_stream_ends_before_terminal(monkeypatch):
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(return_value=None))

    agent_engine = _FakeAgentEngine(events_before_error=2, raise_error=False)
    non_terminal_events = [
        {"content": {"parts": [{"function_response": {"name": "copywriter", "response": {"result": "copy"}}}]}}
    ] * 4
    terminal_events = [
        {"content": {"parts": [{"function_response": {"name": "project_manager", "response": {"result": "timeline"}}}]}}
    ] * 9
    client = _FakeClient(event_batches=[non_terminal_events, terminal_events])

    result = await main._drain(
        client, agent_engine, "session-name", "user-1", "session-1", "Create campaign"
    )
    assert result == 9
    assert agent_engine.calls == 2
    assert agent_engine.messages[1] == main.CONTINUATION_PROMPT


@pytest.mark.asyncio
async def test_drain_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "MAX_DRAIN_RETRIES", 2)

    agent_engine = _FakeAgentEngine(events_before_error=0, raise_error=True, error_on_call=1)
    agent_engine.async_stream_query = lambda user_id, session_id, message: _always_raise()
    non_terminal_events = [
        {"content": {"parts": [{"function_response": {"name": "designer", "response": {"result": "img"}}}]}}
    ] * 3
    client = _FakeClient(event_batches=[non_terminal_events, non_terminal_events, non_terminal_events, non_terminal_events])

    with pytest.raises(RuntimeError) as exc_info:
        await main._drain(client, agent_engine, "session-name", "user-1", "session-1", "brief")
    assert "503 UNAVAILABLE" in str(exc_info.value)


async def _always_raise():
    raise RuntimeError("503 UNAVAILABLE")
    yield
