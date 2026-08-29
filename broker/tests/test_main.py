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
    monkeypatch.setattr(
        auth, "verify_id_token",
        lambda header: auth.AuthenticatedUser(uid="user-123", is_anonymous=False),
    )


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


def test_create_campaign_passes_is_anonymous_through_to_check_admission(monkeypatch):
    """The anonymous-auth lifetime cap (campaign_limits.check_admission's
    is_anonymous kwarg) only applies when the verified token actually came
    from an anonymous sign-in -- this pins down that handle_create_campaign
    forwards auth.AuthenticatedUser.is_anonymous rather than defaulting it.
    """
    monkeypatch.setattr(
        auth, "verify_id_token",
        lambda header: auth.AuthenticatedUser(uid="anon-1", is_anonymous=True),
    )
    check_admission = AsyncMock(return_value={"allowed": True})
    monkeypatch.setattr(campaign_limits, "check_admission", check_admission)
    monkeypatch.setattr(campaign_store, "create_dispatched", AsyncMock())
    monkeypatch.setattr(campaign_queue, "enqueue", AsyncMock())

    resp = _client().post("/campaigns", json={"prompt": "hi"})

    assert resp.status_code == 200
    check_admission.assert_awaited_once_with("anon-1", is_anonymous=True)


def test_create_campaign_returns_429_when_anonymous_lifetime_cap_exceeded(monkeypatch):
    monkeypatch.setattr(
        auth, "verify_id_token",
        lambda header: auth.AuthenticatedUser(uid="anon-1", is_anonymous=True),
    )
    monkeypatch.setattr(
        campaign_limits, "check_admission",
        AsyncMock(return_value={
            "allowed": False, "status": "error",
            "error": "rate_limited: anonymous sessions are limited to 3 campaign starts total. Sign in with a Google account to continue.",
        }),
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(campaign_queue, "enqueue", enqueue)

    resp = _client().post("/campaigns", json={"prompt": "hi"})

    assert resp.status_code == 429
    assert "anonymous" in resp.json()["error"]
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


def test_get_events_cursor_is_never_null_for_a_dispatched_campaign_with_no_events_yet(monkeypatch):
    """Regression: the SPA advances its poll via useInfiniteQuery's
    fetchNextPage(), whose underlying fetch is a no-op when the page param
    (this cursor) is null and a page already exists (see
    @tanstack/query-core's infiniteQueryBehavior.ts). A null cursor here
    the first time a freshly-dispatched campaign (no events, no `since`
    yet) is polled would silently and permanently stop the SPA's poll.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "dispatched", "updated_at": now}),
    )
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [])

    resp = _client().get("/campaigns/s1/events")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "starting"
    assert body["steps"] == []
    assert body["cursor"] is not None


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


def test_get_events_does_not_500_when_sdk_returns_a_real_datetime_timestamp(monkeypatch):
    """Regression, caught by a live e2e test against a real Agent Engine
    session: sessions_client.list_events (backed by the real SDK) returns
    events whose `timestamp` field is a `datetime` object, not a string --
    every prior test here used a pre-stringified timestamp instead, so
    this went undetected until a genuine live run 500'd on every single
    poll (TypeError inside _is_recent's "Z" -> "+00:00" string replace,
    called on a datetime). events_normalizer.py's _timestamp_to_iso is the
    fix; this pins it down through the full route, not just the
    normalizer in isolation.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "running", "updated_at": now}),
    )
    fake_event = {
        "name": "projects/p/locations/l/reasoningEngines/e/sessions/s1/events/1",
        "author": "user",
        "timestamp": now,  # a real datetime, not a string -- the point of this test
        "content": {"parts": [{"text": "hello"}]},
        "actions": {},
    }
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [fake_event])

    resp = _client().get("/campaigns/s1/events")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["cursor"], str)


# ---- POST /campaigns/{id}/resume ----

def test_resume_rejects_unauthenticated(monkeypatch):
    def _raise(header):
        raise auth.AuthError("bad token")
    monkeypatch.setattr(auth, "verify_id_token", _raise)
    resp = _client().post("/campaigns/s1/resume")
    assert resp.status_code == 401


def test_resume_404_when_campaign_missing(monkeypatch):
    monkeypatch.setattr(campaign_store, "get_campaign", AsyncMock(return_value=None))
    resp = _client().post("/campaigns/s1/resume")
    assert resp.status_code == 404


def test_resume_404_when_owned_by_different_user(monkeypatch):
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "someone-else", "status": "failed"}),
    )
    resp = _client().post("/campaigns/s1/resume")
    assert resp.status_code == 404


def test_resume_rejects_when_derived_status_is_running(monkeypatch):
    """doc status "running" with a fresh event must block resume -- it's
    genuinely still in progress.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "running", "updated_at": now}),
    )
    fresh_event = {
        "name": "projects/p/locations/l/reasoningEngines/e/sessions/s1/events/1",
        "author": "creative_director",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "content": {"parts": [{"text": "working"}]},
        "actions": {},
    }
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [fresh_event])
    enqueue = AsyncMock()
    monkeypatch.setattr(campaign_queue, "enqueue", enqueue)

    resp = _client().post("/campaigns/s1/resume")

    assert resp.status_code == 409
    enqueue.assert_not_awaited()


def test_resume_rejects_complete_campaign(monkeypatch):
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "complete"}),
    )
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [])
    enqueue = AsyncMock()
    monkeypatch.setattr(campaign_queue, "enqueue", enqueue)

    resp = _client().post("/campaigns/s1/resume")

    assert resp.status_code == 409
    enqueue.assert_not_awaited()


def test_resume_allowed_for_doc_status_running_but_actually_stalled(monkeypatch):
    """The scenario this route exists for: campaign-driver crashed without
    ever writing `failed`, so the doc still says "running" -- but the last
    event is old enough that the derived status is "stalled", which must
    be resumable.
    """
    long_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "running", "updated_at": long_ago}),
    )
    stale_event = {
        "name": "projects/p/locations/l/reasoningEngines/e/sessions/s1/events/1",
        "author": "creative_director",
        "timestamp": long_ago.isoformat().replace("+00:00", "Z"),
        "content": {"parts": [{"text": "stuck here"}]},
        "actions": {},
    }
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [stale_event])
    monkeypatch.setattr(campaign_limits, "check_admission", AsyncMock(return_value={"allowed": True}))
    enqueue = AsyncMock()
    monkeypatch.setattr(campaign_queue, "enqueue", enqueue)

    resp = _client().post("/campaigns/s1/resume")

    assert resp.status_code == 200
    enqueue.assert_awaited_once()


def test_resume_happy_path_for_failed_campaign(monkeypatch):
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "failed"}),
    )
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [])
    monkeypatch.setattr(campaign_limits, "check_admission", AsyncMock(return_value={"allowed": True}))
    enqueue = AsyncMock()
    monkeypatch.setattr(campaign_queue, "enqueue", enqueue)

    resp = _client().post("/campaigns/s1/resume")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "sessionId": "s1"}
    enqueue.assert_awaited_once()
    assert enqueue.await_args.args[0] == "s1"
    assert enqueue.await_args.args[1] == "user-123"


def test_resume_passes_is_anonymous_through_to_check_admission(monkeypatch):
    """A resume dispatches an equally real, billable campaign-driver run as
    a fresh start, so it must be gated by the same anonymous lifetime cap
    -- otherwise an anonymous user could bypass the cap entirely by
    resuming instead of starting fresh.
    """
    monkeypatch.setattr(
        auth, "verify_id_token",
        lambda header: auth.AuthenticatedUser(uid="anon-1", is_anonymous=True),
    )
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "anon-1", "status": "failed"}),
    )
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [])
    check_admission = AsyncMock(return_value={"allowed": True})
    monkeypatch.setattr(campaign_limits, "check_admission", check_admission)
    monkeypatch.setattr(campaign_queue, "enqueue", AsyncMock())

    resp = _client().post("/campaigns/s1/resume")

    assert resp.status_code == 200
    check_admission.assert_awaited_once_with("anon-1", is_anonymous=True)


def test_resume_returns_429_when_rate_limited(monkeypatch):
    monkeypatch.setattr(
        campaign_store, "get_campaign",
        AsyncMock(return_value={"user_id": "user-123", "status": "failed"}),
    )
    monkeypatch.setattr(sessions_client, "list_events", lambda session_id, since=None: [])
    monkeypatch.setattr(
        campaign_limits, "check_admission",
        AsyncMock(return_value={"allowed": False, "status": "error", "error": "rate_limited: too many"}),
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(campaign_queue, "enqueue", enqueue)

    resp = _client().post("/campaigns/s1/resume")

    assert resp.status_code == 429
    enqueue.assert_not_awaited()


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
