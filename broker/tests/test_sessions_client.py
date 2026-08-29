"""Tests for sessions_client.py's 404-tolerance in list_events.

Caught live, against the real deployed stack: a freshly-dispatched
campaign has an inherent race between the broker enqueueing the Cloud
Tasks dispatch (which returns to the client in ~1s, per the plan) and
campaign-driver actually connecting and creating the session server-side.
The SPA's very first poll can land in that window, before the session
exists at all -- sessions.events.list then 404s, which previously
propagated as an unhandled exception all the way out of
handle_get_events, producing a raw 500 with no CORS header attached
(the exception escapes before Starlette's CORS middleware can write it).
Browsers report a response like that as a misleading "CORS policy" error
rather than the real 500, which is exactly what surfaced in production.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sessions_client  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402


def _make_api_error(code: int) -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"code": code, "message": "not found", "status": "NOT_FOUND"}})


def test_list_events_returns_empty_list_on_404(monkeypatch):
    fake_client = MagicMock()
    fake_client.agent_engines.sessions.events.list.side_effect = _make_api_error(404)
    monkeypatch.setattr(sessions_client, "_get_client", lambda: fake_client)

    result = sessions_client.list_events("does-not-exist-yet")

    assert result == []


def test_list_events_reraises_non_404_api_errors(monkeypatch):
    fake_client = MagicMock()
    fake_client.agent_engines.sessions.events.list.side_effect = _make_api_error(500)
    monkeypatch.setattr(sessions_client, "_get_client", lambda: fake_client)

    with pytest.raises(genai_errors.APIError):
        sessions_client.list_events("some-session")


def test_list_events_reraises_non_api_errors(monkeypatch):
    fake_client = MagicMock()
    fake_client.agent_engines.sessions.events.list.side_effect = RuntimeError("unexpected")
    monkeypatch.setattr(sessions_client, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError):
        sessions_client.list_events("some-session")


def test_list_events_happy_path_still_works(monkeypatch):
    fake_client = MagicMock()
    fake_client.agent_engines.sessions.events.list.return_value = [{"id": "1"}, {"id": "2"}]
    monkeypatch.setattr(sessions_client, "_get_client", lambda: fake_client)

    result = sessions_client.list_events("some-session")

    assert result == [{"id": "1"}, {"id": "2"}]
