"""Unit tests for the anonymous-auth lifetime trigger cap.

Uses a fake Firestore transaction/document layer (no live GCP calls) that
models exactly the read-then-conditionally-write shape
try_acquire_anonymous_lifetime_trigger relies on, so these exercise the
real check-and-increment logic rather than mocking it away.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import campaign_limits as cl  # noqa: E402


class _FakeSnapshot:
    def __init__(self, data: dict | None):
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict:
        return self._data or {}


class _FakeTransaction:
    """Mimics google.cloud.firestore.AsyncTransaction just enough for
    try_acquire_anonymous_lifetime_trigger: get() reads the fake store,
    set() with merge=True increments the stored count.
    """

    def __init__(self, store: dict[str, dict]):
        self._store = store

    def set(self, doc_ref, data, merge=False):
        current = self._store.get(doc_ref.path, {})
        if merge:
            current.update(data)
        else:
            current = data
        self._store[doc_ref.path] = current


class _FakeDocRef:
    def __init__(self, store: dict[str, dict], path: str):
        self._store = store
        self.path = path

    async def get(self, transaction=None):
        return _FakeSnapshot(self._store.get(self.path))


class _FakeCollection:
    def __init__(self, store: dict[str, dict]):
        self._store = store

    def document(self, doc_id: str) -> _FakeDocRef:
        return _FakeDocRef(self._store, doc_id)


class _FakeDb:
    def __init__(self):
        self.store: dict[str, dict] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self.store)

    def transaction(self):
        return _FakeTransaction(self.store)


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(cl, "_get_db", lambda: db)
    monkeypatch.setattr(cl, "ANONYMOUS_MAX_LIFETIME_TRIGGERS", 3)

    # firestore.async_transactional in the real library wraps the function
    # to receive a transaction and run it; here we just call straight
    # through since _FakeTransaction has no real transactional semantics
    # to coordinate.
    import google.cloud.firestore as firestore_module

    def _identity_decorator(fn):
        async def _wrapper(transaction):
            return await fn(transaction)
        return _wrapper

    monkeypatch.setattr(firestore_module, "async_transactional", _identity_decorator)
    return db


async def test_first_three_triggers_are_allowed(fake_db):
    for _ in range(3):
        assert await cl.try_acquire_anonymous_lifetime_trigger("anon-1") is True


async def test_fourth_trigger_is_refused(fake_db):
    for _ in range(3):
        await cl.try_acquire_anonymous_lifetime_trigger("anon-1")
    assert await cl.try_acquire_anonymous_lifetime_trigger("anon-1") is False


async def test_cap_is_never_refilled_by_waiting(fake_db, monkeypatch):
    """Unlike the sliding-window rate limiter, this is a one-way lifetime
    counter -- there is no time-based refill to wait out.
    """
    for _ in range(3):
        await cl.try_acquire_anonymous_lifetime_trigger("anon-1")
    # No time manipulation available or needed: try_acquire_anonymous_lifetime_trigger
    # never reads a clock, so simply calling again (as if "later") still refuses.
    assert await cl.try_acquire_anonymous_lifetime_trigger("anon-1") is False


async def test_cap_is_scoped_per_uid(fake_db):
    for _ in range(3):
        await cl.try_acquire_anonymous_lifetime_trigger("anon-1")
    assert await cl.try_acquire_anonymous_lifetime_trigger("anon-1") is False
    # A different anonymous uid has its own independent budget.
    assert await cl.try_acquire_anonymous_lifetime_trigger("anon-2") is True


async def test_check_admission_refuses_anonymous_user_over_cap(fake_db, monkeypatch):
    monkeypatch.setattr(cl, "try_acquire_rate_limit", AsyncMock(return_value=True))
    for _ in range(3):
        await cl.try_acquire_anonymous_lifetime_trigger("anon-1")

    result = await cl.check_admission("anon-1", is_anonymous=True)

    assert result["allowed"] is False
    assert "anonymous" in result["error"]


async def test_check_admission_does_not_apply_cap_to_non_anonymous_user(fake_db, monkeypatch):
    monkeypatch.setattr(cl, "try_acquire_rate_limit", AsyncMock(return_value=True))
    monkeypatch.setattr(cl, "get_max_concurrent_campaigns", AsyncMock(return_value=5))
    monkeypatch.setattr(cl, "count_active_campaigns", AsyncMock(return_value=0))

    # Even after "using up" 3 anonymous-style triggers under a different
    # uid, a non-anonymous call for the same uid is unaffected -- the cap
    # is gated entirely on is_anonymous, never consulted otherwise.
    for _ in range(5):
        await cl.try_acquire_anonymous_lifetime_trigger("real-user-1")

    result = await cl.check_admission("real-user-1", is_anonymous=False)
    assert result["allowed"] is True


async def test_elevate_user_allowance(fake_db):
    await cl.elevate_user_allowance("user-elevate", max_concurrent=10, tokens=20)
    max_c = await cl.get_max_concurrent_campaigns("user-elevate")
    assert max_c == 10
