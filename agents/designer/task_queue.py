"""Cloud Tasks client for dispatching image generation jobs.

The queue's dispatch rate/concurrency (`max-dispatches-per-second`,
`max-concurrent-dispatches`) is configured entirely at the infrastructure
level (see `deploy/deploy_all_specialists.py`) to match the current Vertex AI
RPM limit -- no custom concurrency-limiting code lives here.
"""
import json
import logging
import os

from google.cloud import tasks_v2

logger = logging.getLogger("ai_creative_studio.designer.task_queue")

GCP_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
GCP_TASKS_LOCATION = os.environ.get("GCP_TASKS_LOCATION", "us-central1")
IMAGE_GEN_TASKS_QUEUE = os.environ.get("IMAGE_GEN_TASKS_QUEUE", "image-generation")
IMAGE_GEN_TASKS_INVOKER_SA = os.environ.get("IMAGE_GEN_TASKS_INVOKER_SA")
IMAGE_GEN_TASK_HANDLER_URL = os.environ.get("IMAGE_GEN_TASK_HANDLER_URL")

_client = None


def _get_client() -> tasks_v2.CloudTasksAsyncClient:
    """Lazily construct a module-level Cloud Tasks async client singleton."""
    global _client
    if _client is None:
        _client = tasks_v2.CloudTasksAsyncClient()
    return _client


async def enqueue(job_id: str, job_kwargs: dict) -> None:
    """Create a Cloud Tasks task that POSTs `{job_id, **job_kwargs}` to the
    internal image-generation handler, authenticated via an OIDC token
    minted for `IMAGE_GEN_TASKS_INVOKER_SA`.
    """
    client = _get_client()
    parent = client.queue_path(GCP_PROJECT_ID, GCP_TASKS_LOCATION, IMAGE_GEN_TASKS_QUEUE)

    payload = {"job_id": job_id, **job_kwargs}
    body = json.dumps(payload).encode()

    task = tasks_v2.Task(
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=IMAGE_GEN_TASK_HANDLER_URL,
            headers={"Content-Type": "application/json"},
            body=body,
            oidc_token=tasks_v2.OidcToken(
                service_account_email=IMAGE_GEN_TASKS_INVOKER_SA,
                audience=IMAGE_GEN_TASK_HANDLER_URL,
            ),
        ),
    )

    request = tasks_v2.CreateTaskRequest(parent=parent, task=task)
    await client.create_task(request=request)
    logger.info(f"Enqueued image generation job {job_id} to Cloud Tasks queue {parent}")
