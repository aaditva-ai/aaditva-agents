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
    """Simulates async_stream_query: fails once mid-stream, then behaves
    according to `post_error_events` on the next call so tests can drive
    both branches of _drain's post-error decision.
    """

    def __init__(self, events_before_error: int, raise_error: bool = True):
        self.events_before_error = events_before_error
        self.raise_error = raise_error
        self.calls = 0

    async def async_stream_query(self, user_id, session_id, message):
        self.calls += 1
        for _ in range(self.events_before_error):
            yield {"author": "x"}
        if self.raise_error and self.calls == 1:
            raise RuntimeError("503 UNAVAILABLE")


class _FakeSessionsEventsList:
    """Simulates client.agent_engines.sessions.events.list(name=...) as a
    sequence of counts returned on successive calls, matching how _drain
    polls the session twice around its sleep to detect growth vs. stability.
    """

    def __init__(self, counts: list[int]):
        self._counts = list(counts)

    def list(self, name):
        n = self._counts.pop(0) if self._counts else self._counts_last
        self._counts_last = n
        return [object()] * n


class _FakeClient:
    def __init__(self, counts: list[int]):
        self.agent_engines = type("_", (), {})()
        self.agent_engines.sessions = type("_", (), {})()
        self.agent_engines.sessions.events = _FakeSessionsEventsList(counts)


@pytest.mark.asyncio
async def test_drain_treats_stable_session_as_complete_after_error(monkeypatch):
    monkeypatch.setattr(main, "asyncio", main.asyncio)  # keep real asyncio.sleep patched below
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(return_value=None))

    agent_engine = _FakeAgentEngine(events_before_error=0, raise_error=True)
    client = _FakeClient(counts=[12, 12])  # stable across the two post-error reads

    result = await main._drain(
        client, agent_engine, "session-name", "user-1", "session-1", "brief"
    )
    assert result == 12
    assert agent_engine.calls == 1  # never retried the stream once treated as complete


@pytest.mark.asyncio
async def test_drain_retries_when_session_still_growing(monkeypatch):
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(return_value=None))

    agent_engine = _FakeAgentEngine(events_before_error=0, raise_error=True)
    # First error triggers a growth check (5 -> 8, growing) then the retried
    # stream call succeeds without raising (calls == 2 skips the raise).
    client = _FakeClient(counts=[5, 8])

    result = await main._drain(
        client, agent_engine, "session-name", "user-1", "session-1", "brief"
    )
    assert result == 0  # second (successful) call yields zero events in this fake
    assert agent_engine.calls == 2


@pytest.mark.asyncio
async def test_drain_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "MAX_DRAIN_RETRIES", 1)

    agent_engine = _FakeAgentEngine(events_before_error=0, raise_error=True)
    agent_engine.async_stream_query = lambda user_id, session_id, message: _always_raise()
    # Always report growth so _drain keeps retrying until it exhausts MAX_DRAIN_RETRIES.
    client = _FakeClient(counts=[1, 2, 3, 4, 5, 6])

    with pytest.raises(RuntimeError):
        await main._drain(client, agent_engine, "session-name", "user-1", "session-1", "brief")


async def _always_raise():
    raise RuntimeError("503 UNAVAILABLE")
    yield  # pragma: no cover -- makes this an async generator
