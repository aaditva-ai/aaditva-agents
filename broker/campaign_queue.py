"""Cloud Tasks client for dispatching campaigns to campaign-driver.

Near-copy of agents/designer/task_queue.py's enqueue pattern, retargeted at
the campaigns queue / campaign-driver's /drive endpoint (plan Proposed
Changes: broker/campaign_queue.py).
"""
import json
import logging
import os

from google.cloud import tasks_v2

logger = logging.getLogger("broker.campaign_queue")

GCP_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
CAMPAIGN_TASKS_LOCATION = os.environ.get("CAMPAIGN_TASKS_LOCATION", "us-central1")
CAMPAIGN_TASKS_QUEUE = os.environ.get("CAMPAIGN_TASKS_QUEUE", "campaigns")
CAMPAIGN_TASKS_INVOKER_SA = os.environ.get("CAMPAIGN_TASKS_INVOKER_SA")
CAMPAIGN_TASK_HANDLER_URL = os.environ.get("CAMPAIGN_TASK_HANDLER_URL")

_client = None


def _get_client() -> tasks_v2.CloudTasksAsyncClient:
    global _client
    if _client is None:
        _client = tasks_v2.CloudTasksAsyncClient()
    return _client


async def enqueue(session_id: str, user_id: str, prompt: str) -> None:
    """Create a Cloud Tasks task that POSTs {sessionId, userId, prompt} to
    campaign-driver's /drive, authenticated via an OIDC token minted for
    CAMPAIGN_TASKS_INVOKER_SA. Returns as soon as the task is created --
    the actual drive happens entirely out of band on campaign-driver.
    """
    client = _get_client()
    parent = client.queue_path(GCP_PROJECT_ID, CAMPAIGN_TASKS_LOCATION, CAMPAIGN_TASKS_QUEUE)

    payload = {"sessionId": session_id, "userId": user_id, "prompt": prompt}
    body = json.dumps(payload).encode()

    task = tasks_v2.Task(
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=CAMPAIGN_TASK_HANDLER_URL,
            headers={"Content-Type": "application/json"},
            body=body,
            oidc_token=tasks_v2.OidcToken(
                service_account_email=CAMPAIGN_TASKS_INVOKER_SA,
                audience=CAMPAIGN_TASK_HANDLER_URL,
            ),
        ),
    )

    request = tasks_v2.CreateTaskRequest(parent=parent, task=task)
    await client.create_task(request=request)
    logger.info(f"Enqueued campaign {session_id} to Cloud Tasks queue {parent}")
