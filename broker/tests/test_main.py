"""Unit tests for the broker's three routes and status-derivation logic.

No live GCP/Firebase calls: auth, campaign_store, campaign_queue,
campaign_limits, and sessions_client are all monkeypatched so these run
offline, exercising the actual routing/validation/status logic.
"""
import datetime
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth  # noqa: E402
import campaign_limits  # noqa: E402
import campaign_queue  # noqa: E402
import campaign_store  # noqa: E402
import main  # noqa: E402
import sessions_client  # noqa: E402


@pytest.fixture(autouse=True)
def _authed(monkeypatch):
    monkeypatch.setattr(auth, "verify_id_token", lambda header: "user-123")


def _client():
    return TestClient(main.app)


# ---- POST /campaigns ----

def test_create_campaign_rejects_unauthenticated(monkeypatch):
    def _raise(header):
        raise auth.AuthError("bad token")
    monkeypatch.setattr(auth, "verify_id_token", _raise)
    resp = _client().post("/campaigns", json={"prompt": "hi"})
    assert resp.status_code == 401


def test_create_campaign_rejects_missing_prompt():
    resp = _client().post("/campaigns", json={})
    assert resp.status_code == 400


def test_create_campaign_happy_path(monkeypatch):
    monkeypatch.setattr(campaign_limits, "check_admission", AsyncMock(return_value={"allowed": True}))
    create_dispatched = AsyncMock()
    enqueue = AsyncMock()
    monkeypatch.setattr(campaign_store, "create_dispatched", create_dispatched)
    monkeypatch.setattr(campaign_queue, "enqueue", enqueue)

    resp = _client().post("/campaigns", json={"prompt": "Make a campaign"})

    assert resp.status_code == 200
    session_id = resp.json()["sessionId"]
    assert session_id
    create_dispatched.assert_awaited_once_with(session_id, "user-123", "Make a campaign")
    enqueue.assert_awaited_once_with(session_id, "user-123", "Make a campaign")


def test_create_campaign_returns_429_when_rate_limited(monkeypatch):
    monkeypatch.setattr(
        campaign_limits, "check_admission",
        AsyncMock(return_value={"allowed": False, "status": "error", "error": "rate_limited: too many"}),
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(campaign_queue, "enqueue", enqueue)

    resp = _client().post("/campaigns", json={"prompt": "hi"})

    assert resp.status_code == 429
    assert "rate_limited" in resp.json()["error"]
    enqueue.assert_not_awaited()


def test_create_campaign_returns_503_when_limiter_unavailable(monkeypatch):
    monkeypatch.setattr(
        campaign_limits, "check_admission",
        AsyncMock(side_effect=RuntimeError("Firestore unavailable")),
    )
    resp = _client().post("/campaigns", json={"prompt": "hi"})
    assert resp.status_code == 503


# ---- GET /campaigns ----

def test_list_campaigns_rejects_unauthenticated(monkeypatch):
    def _raise(header):
        raise auth.AuthError("bad token")
    monkeypatch.setattr(auth, "verify_id_token", _raise)
    resp = _client().get("/campaigns")
    assert resp.status_code == 401


def test_list_campaigns_maps_fields(monkeypatch):
    docs = [
        {
            "session_id": "s1",
            "prompt": "x" * 200,
            "status": "running",
            "created_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            "updated_at": datetime.datetime(2026, 1, 1, 0, 5, tzinfo=datetime.timezone.utc),
        }
    ]
    monkeypatch.setattr(campaign_store, "list_campaigns_for_user", AsyncMock(return_value=docs))

    resp = _client().get("/campaigns")

    assert resp.status_code == 200
    campaigns = resp.json()["campaigns"]
    assert len(campaigns) == 1
    assert campaigns[0]["sessionId"] == "s1"
    assert len(campaigns[0]["title"]) == main.TITLE_MAX_CHARS
    assert campaigns[0]["status"] == "running"


# ---- GET /campaigns/{id}/events ----

def test_get_events_404_when_campaign_missing(monkeypatch):
    monkeypatch.setattr(campaign_store, "get_campaign", AsyncMock(return_value=None))
    resp = _client().get("/campaigns/s1/events")
    assert resp.status_code == 404


def test_get_events_404_when_owned_by_different_user(monkeypatch):
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "someone-else", "status": "running"}),
    )
    resp = _client().get("/campaigns/s1/events")
    assert resp.status_code == 404


def test_get_events_no_new_steps_uses_since_not_stale_doc_updated_at(monkeypatch):
    """Regression: a healthy campaign with a multi-minute gap between
    specialist calls (Step 1 observed exactly this) must not be reported
    `stalled` just because the campaign document's own `updated_at` (set
    once, at mark_running) is old and this particular poll had zero new
    events. Freshness must be judged against `since` (the client's last
    known cursor), not the driver's status-transition timestamp.
    """
    long_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    recent_since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "running", "updated_at": long_ago}),
    )
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [])

    resp = _client().get(f"/campaigns/s1/events?since={recent_since}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_get_events_happy_path(monkeypatch):
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "running", "updated_at": now}),
    )
    fake_event = {
        "name": "projects/p/locations/l/reasoningEngines/e/sessions/s1/events/1",
        "author": "user",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "content": {"parts": [{"text": "hello"}]},
        "actions": {},
    }
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [fake_event])

    resp = _client().get("/campaigns/s1/events")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert len(body["steps"]) == 1
    assert body["steps"][0]["kind"] == "text"
    assert body["cursor"]


# ---- _derive_status ----

def test_derive_status_none_doc_is_failed():
    assert main._derive_status(None, True) == "failed"


@pytest.mark.parametrize("terminal_status", ["complete", "failed"])
def test_derive_status_terminal_doc_status_wins_even_if_stale(terminal_status):
    doc = {"status": terminal_status}
    assert main._derive_status(doc, False) == terminal_status


def test_derive_status_dispatched_and_recent_is_starting():
    doc = {"status": "dispatched"}
    assert main._derive_status(doc, True) == "starting"


def test_derive_status_dispatched_and_stale_is_stalled():
    doc = {"status": "dispatched"}
    assert main._derive_status(doc, False) == "stalled"


def test_derive_status_running_and_recent_is_running():
    doc = {"status": "running"}
    assert main._derive_status(doc, True) == "running"


def test_derive_status_running_and_stale_is_stalled():
    """The regression this guards: a running campaign with no *new* steps
    on this particular poll (is_recent derived from `since`, not from
    whether this page had anything) must still read "running" while
    healthy -- only actual staleness should flip it to "stalled".
    """
    doc = {"status": "running"}
    assert main._derive_status(doc, False) == "stalled"
