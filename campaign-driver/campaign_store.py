"""Firestore-backed campaign document store.

This is the one piece of state the driver owns. Agent Engine's session
already persists every event durably (confirmed in scripts/spikes/), so the
campaign document exists only to answer "is this session still being worked
on, and by whom" -- the thing sessions.events.list alone cannot say. See
agents/designer/job_store.py for the equivalent pattern this mirrors.
"""
import logging

from google.cloud import firestore

logger = logging.getLogger("campaign_driver.campaign_store")

_COLLECTION = "campaigns"

_db = None


def _get_db() -> firestore.AsyncClient:
    """Lazily construct a module-level Firestore async client singleton."""
    global _db
    if _db is None:
        _db = firestore.AsyncClient()
    return _db


def _doc(session_id: str):
    return _get_db().collection(_COLLECTION).document(session_id)


async def create_dispatched(session_id: str, user_id: str, prompt: str) -> None:
    """Create the campaign document in `dispatched` state, before enqueueing
    the Cloud Tasks task. Safe to call again for the same session_id (e.g. a
    resume) -- merges rather than overwrites so `created_at` and prior
    history are preserved.
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


async def mark_running(session_id: str) -> bool:
    """Transition `dispatched` -> `running`, guarding re-entry.

    Returns False (and does not write) if the document is already `running`
    or terminal (`complete`/`failed`) -- this is what stops a re-delivered
    Cloud Tasks push (or a stray duplicate) from starting a second drive on
    a session that is already being driven or has already finished. Step 1's
    spike_resume showed the ADK runner itself continues cleanly from session
    history, so this guard exists purely to stop *concurrent* drives, not to
    block a legitimate resume -- resume goes through this same function and
    is expected to only proceed when the prior run is no longer `running`.
    """
    db = _get_db()
    doc_ref = _doc(session_id)

    @firestore.async_transactional
    async def _run(transaction: firestore.AsyncTransaction) -> bool:
        snapshot = await doc_ref.get(transaction=transaction)
        if snapshot.exists:
            status = snapshot.to_dict().get("status")
            if status == "running":
                return False
        transaction.set(
            doc_ref,
            {"status": "running", "updated_at": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
        return True

    transaction = db.transaction()
    return await _run(transaction)


async def mark_complete(session_id: str, event_count: int) -> None:
    await _doc(session_id).set(
        {
            "status": "complete",
            "event_count": event_count,
            "error": None,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )


async def mark_failed(session_id: str, error: str) -> None:
    await _doc(session_id).set(
        {
            "status": "failed",
            "error": error,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )


async def get_campaign(session_id: str) -> dict | None:
    snapshot = await _doc(session_id).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict()
