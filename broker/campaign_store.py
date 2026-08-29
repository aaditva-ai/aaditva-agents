"""Firestore-backed campaign document access for the broker.

Reads/writes the same `campaigns` collection campaign-driver owns (see
campaign-driver/campaign_store.py) -- the broker creates the `dispatched`
document and reads status for GET /campaigns and the events route;
campaign-driver owns every subsequent transition. Kept as its own copy
rather than a shared package, consistent with how agents/designer/ and this
plan's other services each carry their own small Firestore modules.
"""
import logging

from google.cloud import firestore

logger = logging.getLogger("broker.campaign_store")

_COLLECTION = "campaigns"

_db = None


def _get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        _db = firestore.AsyncClient()
    return _db


def _doc(session_id: str):
    return _get_db().collection(_COLLECTION).document(session_id)


async def create_dispatched(session_id: str, user_id: str, prompt: str) -> None:
    """Create the campaign document in `dispatched` state before enqueueing
    the Cloud Tasks task. This is the idempotency record for the session --
    campaign-driver's mark_running refuses to start a second concurrent
    drive against it.
    """
    now = firestore.SERVER_TIMESTAMP
    await _doc(session_id).set(
        {
            "session_id": session_id,
            "user_id": user_id,
            "prompt": prompt,
            "status": "dispatched",
            "error": None,
            "created_at": now,
            "updated_at": now,
        },
        merge=True,
    )


async def get_campaign(session_id: str) -> dict | None:
    snapshot = await _doc(session_id).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict()


async def list_campaigns_for_user(user_id: str, limit: int = 50) -> list[dict]:
    """Return the caller's campaign documents, most recently created first --
    the server-side replacement for localStorage (plan Key Decision #5/#6,
    Functional Requirement 4a).
    """
    db = _get_db()
    query = (
        db.collection(_COLLECTION)
        .where("user_id", "==", user_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [doc.to_dict() async for doc in query.stream()]
