"""Firestore-backed job store bridging the Cloud Tasks handler and the waiting
`generate_image` coroutine, which may be running on a different Cloud Run
instance than the one that eventually handles the task.
"""
import asyncio
import logging
import os
import uuid

from google.cloud import firestore

logger = logging.getLogger("ai_creative_studio.designer.job_store")

JOB_POLL_INTERVAL_SECONDS = float(os.environ.get("IMAGE_GEN_JOB_POLL_INTERVAL_SECONDS", "1"))
JOB_TIMEOUT_SECONDS = float(os.environ.get("IMAGE_GEN_JOB_TIMEOUT_SECONDS", "170"))

_COLLECTION = "image_gen_jobs"

_db = None


def _get_db() -> firestore.AsyncClient:
    """Lazily construct a module-level Firestore async client singleton."""
    global _db
    if _db is None:
        _db = firestore.AsyncClient()
    return _db


async def create_job(job_kwargs: dict) -> str:
    """Create a pending `image_gen_jobs/{job_id}` document and return its id."""
    db = _get_db()
    job_id = uuid.uuid4().hex
    doc_ref = db.collection(_COLLECTION).document(job_id)
    now = firestore.SERVER_TIMESTAMP
    await doc_ref.set(
        {
            "status": "pending",
            "concept_name": job_kwargs.get("concept_name"),
            "gcs_uri": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    return job_id


async def complete_job(job_id: str, result: dict) -> None:
    """Write the final result payload to the job document.

    Safe to call more than once for the same `job_id` (Cloud Tasks may retry
    the handler after a transient failure); last write wins.
    """
    db = _get_db()
    doc_ref = db.collection(_COLLECTION).document(job_id)
    await doc_ref.set(
        {
            "status": result.get("status", "error"),
            "gcs_uri": result.get("gcs_uri"),
            "error": result.get("error"),
            "concept_name": result.get("concept_name"),
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )


async def poll_job(
    job_id: str,
    timeout_s: float = JOB_TIMEOUT_SECONDS,
    interval_s: float = JOB_POLL_INTERVAL_SECONDS,
) -> dict:
    """Poll `image_gen_jobs/{job_id}` until it leaves the "pending" status.

    Returns the job document's result-shaped fields, or a structured timeout
    error if `timeout_s` elapses without a terminal status.
    """
    db = _get_db()
    doc_ref = db.collection(_COLLECTION).document(job_id)

    elapsed = 0.0
    while elapsed < timeout_s:
        snapshot = await doc_ref.get()
        if snapshot.exists:
            data = snapshot.to_dict()
            if data.get("status") != "pending":
                return {
                    "status": data.get("status"),
                    "gcs_uri": data.get("gcs_uri"),
                    "error": data.get("error"),
                    "concept_name": data.get("concept_name"),
                }
        await asyncio.sleep(interval_s)
        elapsed += interval_s

    logger.error(f"Timed out waiting for image generation job {job_id} to complete.")
    return {
        "status": "error",
        "error": f"Image generation timed out after {timeout_s} seconds (job_id={job_id}).",
    }
