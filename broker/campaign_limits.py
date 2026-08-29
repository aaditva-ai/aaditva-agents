"""Firestore-backed per-user token bucket + concurrent-campaign allowance.

Near-copy of agents/designer/rate_limiter.py's transactional token bucket,
extended with the per-user concurrent-campaign count the plan calls for
(Functional Requirement 5a, Key Decision #2a) -- the hook a future "add
credits" flow writes to, per the plan's framing.
"""
import logging
import os
import time

from google.cloud import firestore

logger = logging.getLogger("broker.campaign_limits")


def _unwrap_root_cause(e: Exception) -> Exception:
    """See agents/designer/rate_limiter.py's identical helper: Firestore's
    async_transactional decorator swallows the real failure (e.g.
    PermissionDenied when Firestore isn't provisioned) behind a misleading
    rollback ValueError.
    """
    seen = set()
    current = e
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValueError) and "cannot be rolled back" in str(current):
            current = current.__cause__ or current.__context__
            continue
        return current
    return e


RATE_LIMIT_CAPACITY = float(os.environ.get("CAMPAIGN_RATE_LIMIT_CAPACITY", "3"))
RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get("CAMPAIGN_RATE_LIMIT_WINDOW_SECONDS", "3600"))
DEFAULT_MAX_CONCURRENT_CAMPAIGNS = int(os.environ.get("CAMPAIGN_MAX_CONCURRENT_DEFAULT", "1"))

_RATE_LIMIT_COLLECTION = "campaign_rate_limits"
_CAMPAIGNS_COLLECTION = "campaigns"
_ALLOWANCE_COLLECTION = "campaign_allowances"

_db = None


def _get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        _db = firestore.AsyncClient()
    return _db


async def try_acquire_rate_limit(user_id: str) -> bool:
    """Consume one token from `user_id`'s bucket. See
    agents/designer/rate_limiter.py's try_acquire for the full algorithm
    this mirrors exactly, just against a campaign-scoped collection/window.
    """
    db = _get_db()
    doc_ref = db.collection(_RATE_LIMIT_COLLECTION).document(user_id)

    @firestore.async_transactional
    async def _run(transaction: firestore.AsyncTransaction) -> bool:
        snapshot = await doc_ref.get(transaction=transaction)
        now = time.time()

        if snapshot.exists:
            data = snapshot.to_dict()
            tokens = data.get("tokens", RATE_LIMIT_CAPACITY)
            last_refill_ts = data.get("last_refill_ts", now)
        else:
            tokens = RATE_LIMIT_CAPACITY
            last_refill_ts = now

        elapsed = max(0.0, now - last_refill_ts)
        refill_rate = RATE_LIMIT_CAPACITY / RATE_LIMIT_WINDOW_SECONDS
        tokens = min(RATE_LIMIT_CAPACITY, tokens + elapsed * refill_rate)

        if tokens < 1.0:
            transaction.set(doc_ref, {"tokens": tokens, "last_refill_ts": now})
            return False

        tokens -= 1.0
        transaction.set(doc_ref, {"tokens": tokens, "last_refill_ts": now})
        return True

    transaction = db.transaction()
    try:
        return await _run(transaction)
    except Exception as e:
        root_cause = _unwrap_root_cause(e)
        logger.error(
            "Firestore rate-limit check failed for user_id=%s: %s. "
            "Ensure Firestore is provisioned (see agents/designer/rate_limiter.py's "
            "identical note).",
            user_id, root_cause,
        )
        raise RuntimeError(f"Rate limiter unavailable: {root_cause}") from root_cause


async def get_max_concurrent_campaigns(user_id: str) -> int:
    """Per-user override, or DEFAULT_MAX_CONCURRENT_CAMPAIGNS if none is set.

    A future credits top-up is a write to campaign_allowances/{user_id}'s
    max_concurrent field -- no code change (plan Key Decision #2a).
    """
    db = _get_db()
    snapshot = await db.collection(_ALLOWANCE_COLLECTION).document(user_id).get()
    if snapshot.exists:
        value = snapshot.to_dict().get("max_concurrent")
        if isinstance(value, int) and value > 0:
            return value
    return DEFAULT_MAX_CONCURRENT_CAMPAIGNS


async def count_active_campaigns(user_id: str) -> int:
    """Count non-terminal (`dispatched`/`running`) campaign documents for
    `user_id` -- the concurrency half of the admission check, separate from
    the token-bucket rate above.
    """
    db = _get_db()
    query = (
        db.collection(_CAMPAIGNS_COLLECTION)
        .where("user_id", "==", user_id)
        .where("status", "in", ["dispatched", "running"])
    )
    count_result = await query.count().get()
    # AsyncAggregationQuery.get() returns a list of lists of AggregationResult.
    return int(count_result[0][0].value)


async def check_admission(user_id: str) -> dict:
    """Combined rate + concurrency gate for POST /campaigns.

    Returns {"allowed": True} or a structured refusal matching the shape
    already used by generate_image's rate limiting:
    {"status": "error", "error": "rate_limited: ..."}
    (plan Functional Requirement 5a).
    """
    allowed_by_rate = await try_acquire_rate_limit(user_id)
    if not allowed_by_rate:
        return {
            "allowed": False,
            "status": "error",
            "error": (
                f"rate_limited: you've started {int(RATE_LIMIT_CAPACITY)} campaigns "
                f"in the last {int(RATE_LIMIT_WINDOW_SECONDS / 60)} minutes. "
                "Please wait before starting another."
            ),
        }

    max_concurrent = await get_max_concurrent_campaigns(user_id)
    active = await count_active_campaigns(user_id)
    if active >= max_concurrent:
        return {
            "allowed": False,
            "status": "error",
            "error": (
                f"rate_limited: you already have {active} campaign(s) in progress "
                f"(limit: {max_concurrent}). Wait for one to finish before starting another."
            ),
        }

    return {"allowed": True}
