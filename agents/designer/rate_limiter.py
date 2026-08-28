"""Firestore-backed per-user token bucket rate limiter for image generation.

Guards against a single user (opening several chat tabs/sessions) exhausting
the shared Vertex AI RPM quota. Backed by Firestore transactions so the bucket
is correct across all Cloud Run instances, unlike an in-memory dict.
"""
import logging
import os
import time

from google.cloud import firestore

logger = logging.getLogger("ai_creative_studio.designer.rate_limiter")


def _unwrap_root_cause(e: Exception) -> Exception:
    """
    Walk `__cause__`/`__context__` to find the real originating error.

    Firestore's `async_transactional` decorator swallows the actual failure
    (e.g. `PermissionDenied` when the Firestore API/database isn't set up)
    when it tries to roll back a transaction that never began, re-raising a
    misleading `ValueError: The transaction has no transaction ID, so it
    cannot be rolled back.` instead. Surfacing the wrapped cause makes the
    real problem (Firestore not enabled/provisioned, bad credentials, etc.)
    visible instead of this confusing rollback error.
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


RATE_LIMIT_CAPACITY = float(os.environ.get("IMAGE_GEN_RATE_LIMIT_CAPACITY", "3"))
RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get("IMAGE_GEN_RATE_LIMIT_WINDOW_SECONDS", "60"))

_COLLECTION = "image_gen_rate_limits"

_db = None


def _get_db() -> firestore.AsyncClient:
    """Lazily construct a module-level Firestore async client singleton."""
    global _db
    if _db is None:
        _db = firestore.AsyncClient()
    return _db


async def try_acquire(user_id: str) -> bool:
    """
    Attempt to consume one token from `user_id`'s bucket.

    Refills tokens based on elapsed time since the last refill (up to
    RATE_LIMIT_CAPACITY), then decrements a token if one is available.
    The read-refill-decrement-write sequence runs inside a Firestore
    transaction so concurrent requests from the same user (e.g. multiple
    tabs landing on different Cloud Run instances) don't race each other.

    Returns True if the request may proceed, False if the user is
    currently rate-limited.
    """
    db = _get_db()
    doc_ref = db.collection(_COLLECTION).document(user_id)

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
            "Ensure the Cloud Firestore API is enabled AND a Firestore database "
            "has been created for this project (`gcloud firestore databases "
            "create --location=<region> --type=firestore-native`) -- enabling "
            "the API alone does not create the database.",
            user_id,
            root_cause,
        )
        raise RuntimeError(
            f"Rate limiter unavailable: {root_cause}"
        ) from root_cause
