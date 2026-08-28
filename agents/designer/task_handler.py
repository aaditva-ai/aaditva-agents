"""Internal HTTP handler that Cloud Tasks pushes to for image generation jobs.

Mounted on the Designer's existing Starlette/A2A app (see `agent.py`'s
`__main__` block) at `/internal/tasks/generate-image`. Verifies the Cloud
Tasks OIDC identity token before doing any work, runs the actual Vertex AI
generation, and writes the result back to the Firestore job document.
"""
import logging
import os

from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token
from starlette.requests import Request
from starlette.responses import JSONResponse

try:
    from . import job_store
    from .image_gen_tool import _run_image_generation
except ImportError:
    import job_store
    from image_gen_tool import _run_image_generation

logger = logging.getLogger("ai_creative_studio.designer.task_handler")

IMAGE_GEN_TASKS_INVOKER_SA = os.environ.get("IMAGE_GEN_TASKS_INVOKER_SA")
IMAGE_GEN_TASK_HANDLER_URL = os.environ.get("IMAGE_GEN_TASK_HANDLER_URL")

_auth_request = google_auth_requests.Request()


def _verify_cloud_tasks_oidc_token(authorization_header: str) -> bool:
    """Verify the `Authorization: Bearer <OIDC token>` header Cloud Tasks
    attaches to its push requests, checking both the audience and the
    invoker service account identity.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return False

    token = authorization_header.removeprefix("Bearer ").strip()
    try:
        claims = id_token.verify_oauth2_token(
            token, _auth_request, audience=IMAGE_GEN_TASK_HANDLER_URL
        )
    except Exception:
        logger.exception("Failed to verify Cloud Tasks OIDC token")
        return False

    return claims.get("email") == IMAGE_GEN_TASKS_INVOKER_SA


async def handle_generate_image_task(request: Request) -> JSONResponse:
    """Starlette route handler for Cloud Tasks push requests."""
    if not _verify_cloud_tasks_oidc_token(request.headers.get("Authorization", "")):
        logger.warning("Rejected image generation task with invalid/missing OIDC token")
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    job_id = payload.get("job_id")
    if not job_id:
        return JSONResponse({"error": "missing job_id"}, status_code=400)

    try:
        result = await _run_image_generation(
            concept_name=payload.get("concept_name"),
            image_prompt=payload.get("image_prompt"),
            aspect_ratio=payload.get("aspect_ratio"),
            project_id=payload.get("project_id"),
            bucket_name=payload.get("bucket_name"),
        )
    except Exception as e:
        logger.exception(f"Unexpected failure running image generation job {job_id}")
        # Let Cloud Tasks retry per the queue's retryConfig instead of
        # writing a terminal failure for a possibly-transient error.
        return JSONResponse({"error": str(e)}, status_code=500)

    # Always complete the Firestore job document immediately, even for a
    # retryable (quota-exhausted) error, so the `generate_image` coroutine
    # polling this job -- and the orchestrator waiting on it -- gets an
    # error back right away instead of hanging until the job-poll timeout.
    await job_store.complete_job(job_id, result)

    if result.get("status") == "error" and result.get("retryable"):
        logger.warning(
            f"Image generation job {job_id} hit a transient rate limit across "
            "all regions; returning an error to Cloud Tasks so it retries the "
            "task per the queue's retryConfig."
        )
        return JSONResponse(
            {"status": "error", "job_id": job_id, "error": result.get("error")},
            status_code=429,
        )

    return JSONResponse({"status": "ok", "job_id": job_id})
