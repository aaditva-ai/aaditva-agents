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


RATE_LIMIT_CAPACITY = float(os.environ.get("CAMPAIGN_RATE_LIMIT_CAPACITY", "20"))
RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get("CAMPAIGN_RATE_LIMIT_WINDOW_SECONDS", "3600"))
DEFAULT_MAX_CONCURRENT_CAMPAIGNS = int(os.environ.get("CAMPAIGN_MAX_CONCURRENT_DEFAULT", "10"))

# A hard, non-refilling lifetime cap on Firebase Anonymous Auth users,
# separate from and in addition to the sliding-window rate limiter above.
# Anonymous Auth issues a fresh uid per browser/device with no identity
# verification, so the ordinary per-window rate limit alone doesn't bound
# total cost from a single anonymous visitor the way it does for a real
# (Google-)authenticated account -- this is the requested "no more than 3
# triggers per id" guard. Applied to both a fresh campaign start and a
# resume (see main.py), since a resume dispatches an equally real,
# billable campaign-driver run and would otherwise let an anonymous user
# work around the cap entirely by resuming indefinitely.
ANONYMOUS_MAX_LIFETIME_TRIGGERS = int(os.environ.get("CAMPAIGN_ANONYMOUS_MAX_TRIGGERS", "30"))

_RATE_LIMIT_COLLECTION = "campaign_rate_limits"
_CAMPAIGNS_COLLECTION = "campaigns"
_ALLOWANCE_COLLECTION = "campaign_allowances"
_ANONYMOUS_USAGE_COLLECTION = "campaign_anonymous_usage"

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


async def elevate_user_allowance(user_id: str, max_concurrent: int = 10, tokens: int = 20) -> None:
    """Explicitly elevates a user's concurrent campaign allowance and refills rate limit tokens."""
    db = _get_db()
    try:
        await db.collection(_ALLOWANCE_COLLECTION).document(user_id).set(
            {"max_concurrent": max_concurrent, "updated_at": time.time()},
            merge=True,
        )
        await db.collection(_RATE_LIMIT_COLLECTION).document(user_id).set(
            {"tokens": float(tokens), "last_refill_ts": time.time()},
            merge=True,
        )
        logger.info("Elevated campaign allowance and refilled tokens for user %s (max_concurrent=%d)", user_id, max_concurrent)
    except Exception as e:
        logger.warning("Could not elevate Firestore user allowance for %s: %s", user_id, e)


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


async def try_acquire_anonymous_lifetime_trigger(user_id: str) -> bool:
    """Atomically check-and-increment `user_id`'s lifetime trigger count,
    capped at ANONYMOUS_MAX_LIFETIME_TRIGGERS. Unlike the token bucket
    above, this never refills -- it's a one-way lifetime counter, since the
    point is to bound total cost from a single anonymous identity rather
    than to smooth request rate.

    Runs inside a transaction so two concurrent requests from the same
    anonymous uid (e.g. a double-click, or a resume racing a fresh start)
    cannot both read the same pre-increment count and both be admitted one
    over the cap.
    """
    db = _get_db()
    doc_ref = db.collection(_ANONYMOUS_USAGE_COLLECTION).document(user_id)

    @firestore.async_transactional
    async def _run(transaction: firestore.AsyncTransaction) -> bool:
        snapshot = await doc_ref.get(transaction=transaction)
        count = snapshot.to_dict().get("trigger_count", 0) if snapshot.exists else 0

        if count >= ANONYMOUS_MAX_LIFETIME_TRIGGERS:
            return False

        transaction.set(doc_ref, {"trigger_count": count + 1}, merge=True)
        return True

    transaction = db.transaction()
    try:
        return await _run(transaction)
    except Exception as e:
        root_cause = _unwrap_root_cause(e)
        logger.error(
            "Firestore anonymous-trigger-cap check failed for user_id=%s: %s.",
            user_id, root_cause,
        )
        raise RuntimeError(f"Rate limiter unavailable: {root_cause}") from root_cause


async def check_admission(user_id: str, is_anonymous: bool = False) -> dict:
    """Combined rate + concurrency (+ anonymous lifetime cap) gate for
    POST /campaigns and POST /campaigns/{id}/resume.

    Returns {"allowed": True} or a structured refusal matching the shape
    already used by generate_image's rate limiting:
    {"status": "error", "error": "rate_limited: ..."}
    (plan Functional Requirement 5a).

    The anonymous cap is checked first: it's a strictly tighter, one-way
    lifetime limit, so there's no reason to also spend a rate-limit token
    for a request that's about to be refused anyway.
    """
    if is_anonymous:
        allowed_by_lifetime_cap = await try_acquire_anonymous_lifetime_trigger(user_id)
        if not allowed_by_lifetime_cap:
            return {
                "allowed": False,
                "status": "error",
                "error": (
                    f"rate_limited: anonymous sessions are limited to "
                    f"{ANONYMOUS_MAX_LIFETIME_TRIGGERS} campaign starts total. "
                    "Sign in with a Google account to continue."
                ),
            }

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
