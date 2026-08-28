"""Gemini native image generation tool. Generates image, uploads to GCS, returns URI."""
import io
import logging
import os
import time
import uuid

from google import genai
from google.adk.tools import ToolContext
from google.cloud import storage
from google.genai import types

try:
    from . import job_store
    from . import rate_limiter
    from . import task_queue
except ImportError:
    import job_store
    import rate_limiter
    import task_queue

logger = logging.getLogger("ai_creative_studio.designer.image_gen")


async def generate_image(
    concept_name: str,
    image_prompt: str,
    aspect_ratio: str,
    tool_context: ToolContext,
) -> dict:
    """
    Generate an image with Gemini native image generation and upload it to GCS.

    Args:
        concept_name: Short identifier for this image concept (e.g. "post1_concept_a")
        image_prompt: Full image generation prompt string
        aspect_ratio: "1:1" for square (1080x1080) or "4:5" for portrait (1080x1350)

    Returns:
        {"status": "success", "gcs_uri": "gs://...", "concept_name": "..."}
        or {"status": "error", "error": "..."}
    """
    user_id = getattr(tool_context, "user_id", None) or "unknown"
    try:
        rate_limit_ok = await rate_limiter.try_acquire(user_id)
    except Exception as e:
        logger.exception(f"Rate limiter backend unavailable for user_id={user_id}")
        return {
            "status": "error",
            "error": (
                f"Image generation backend unavailable: {e}. Check that the "
                "Cloud Firestore API is enabled and a Firestore database has "
                "been created for this project."
            ),
        }
    if not rate_limit_ok:
        return {
            "status": "error",
            "error": (
                "rate_limited: too many image generation requests for this user; "
                "please wait before generating more images."
            ),
        }

    bucket_name = os.environ.get("GCS_IMAGES_BUCKET")
    if not bucket_name:
        return {
            "status": "error",
            "error": "GCS_IMAGES_BUCKET environment variable is not configured.",
        }

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        return {
            "status": "error",
            "error": "GOOGLE_CLOUD_PROJECT environment variable is not configured.",
        }

    job_kwargs = {
        "concept_name": concept_name,
        "image_prompt": image_prompt,
        "aspect_ratio": aspect_ratio,
        "project_id": project_id,
        "bucket_name": bucket_name,
    }

    try:
        job_id = await job_store.create_job(job_kwargs)
        await task_queue.enqueue(job_id, job_kwargs)
        result = await job_store.poll_job(job_id)
    except Exception as e:
        logger.exception(f"Failed to queue/poll image generation job for {concept_name}")
        return {
            "status": "error",
            "error": (
                f"Image generation backend unavailable: {e}. Check that the "
                "Cloud Firestore API/database and the Cloud Tasks queue are "
                "provisioned for this project, and that IMAGE_GEN_TASK_HANDLER_URL "
                "is a real, publicly reachable HTTPS URL (e.g. a Cloud Run "
                "deployment of the Designer, since Cloud Tasks cannot reach "
                "localhost)."
            ),
        }

    # Save ADK artifact for local developer UI rendering, re-downloading the
    # just-uploaded GCS bytes (only `generate_image` has `tool_context`; the
    # decoupled Cloud Tasks handler does not).
    if result.get("status") == "success" and tool_context and result.get("gcs_uri"):
        try:
            gcs_uri = result["gcs_uri"]
            _, _, path = gcs_uri.partition("gs://")
            uri_bucket_name, _, blob_name = path.partition("/")
            ext = blob_name.rsplit(".", 1)[-1] if "." in blob_name else "png"
            mime_type = "image/jpeg" if ext == "jpg" else "image/png"

            gcs_client = storage.Client(project=project_id)
            blob = gcs_client.bucket(uri_bucket_name).blob(blob_name)
            image_bytes = blob.download_as_bytes()

            artifact = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            await tool_context.save_artifact(f"{concept_name}.{ext}", artifact)
        except Exception:
            logger.exception(f"Failed to save ADK artifact for {concept_name}")

    return {
        "status": result.get("status", "error"),
        "gcs_uri": result.get("gcs_uri"),
        "concept_name": result.get("concept_name", concept_name),
        **({"error": result["error"]} if result.get("error") else {}),
        # Surface `retryable` (set by `_run_image_generation` for a
        # quota-exhaustion failure) so the calling agent -- and ultimately
        # the Creative Director orchestrator -- knows this specific error
        # is transient and worth retrying, rather than a hard failure.
        **({"retryable": True} if result.get("retryable") else {}),
    }


def _is_quota_exhausted_error(e: Exception) -> bool:
    """True if `e` represents a 429 / RESOURCE_EXHAUSTED response."""
    code = getattr(e, "code", None)
    if code == 429:
        return True
    return "RESOURCE_EXHAUSTED" in str(e).upper()


# Number of in-region retry attempts for a 429/RESOURCE_EXHAUSTED response
# before failing over to the next region (or giving up, if this is the last
# or only region -- e.g. when IMAGE_GEN_REGIONS has fallen back to just
# "global" because no other region actually serves the configured model).
# Concurrent concept image generations (typically 3 per design request) can
# briefly burst past the project's per-minute quota on a single endpoint;
# a short backoff-and-retry here gives that quota a chance to free up
# instead of surfacing a hard failure immediately.
_QUOTA_RETRY_ATTEMPTS = 3
_QUOTA_RETRY_BASE_DELAY_SECONDS = 4


def _generate_with_region_failover(
    regions: list,
    project_id: str,
    image_model: str,
    prompt_with_aspect: str,
):
    """
    Call `generate_content` against each region in `regions` in order.

    On a 429/RESOURCE_EXHAUSTED response from a region, retries the same
    region up to `_QUOTA_RETRY_ATTEMPTS` times with exponential backoff
    (since a single region -- e.g. a "global"-only fallback list -- may be
    the only option, so failing over immediately would just raise). Once
    those in-region retries are exhausted, fails over to the next region
    without waiting further. Backoff for 500/503/504 is preserved
    *within* each individual call via `retry_options` below. Re-raises the
    last exception once all regions (and their retries) are exhausted.
    """
    retry_options = types.HttpRetryOptions(
        attempts=3,
        exp_base=2,
        initial_delay=5,
        http_status_codes=[500, 503, 504],
    )

    last_exception = None
    for region in regions:
        region = region.strip()
        client = genai.Client(vertexai=True, project=project_id, location=region)
        for attempt in range(1, _QUOTA_RETRY_ATTEMPTS + 1):
            try:
                return client.models.generate_content(
                    model=image_model,
                    contents=prompt_with_aspect,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                        http_options=types.HttpOptions(
                            retry_options=retry_options,
                            timeout=180_000,
                        ),
                    ),
                )
            except Exception as e:
                last_exception = e
                if not _is_quota_exhausted_error(e):
                    raise
                if attempt < _QUOTA_RETRY_ATTEMPTS:
                    delay = _QUOTA_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        f"Region {region} returned 429/RESOURCE_EXHAUSTED "
                        f"(attempt {attempt}/{_QUOTA_RETRY_ATTEMPTS}), "
                        f"retrying in {delay}s"
                    )
                    time.sleep(delay)
                else:
                    logger.warning(
                        f"Region {region} still 429/RESOURCE_EXHAUSTED after "
                        f"{_QUOTA_RETRY_ATTEMPTS} attempts, failing over to next region"
                    )

    raise last_exception


async def _run_image_generation(
    concept_name: str,
    image_prompt: str,
    aspect_ratio: str,
    project_id: str,
    bucket_name: str,
) -> dict:
    """
    Perform the actual Vertex AI image generation, validation, and GCS upload.

    Invoked from the Cloud Tasks handler (`task_handler.py`), decoupled from
    the ADK `generate_image` tool-call coroutine. Does not perform ADK
    artifact saving, since that requires the original `ToolContext`.
    """
    regions = os.environ.get("IMAGE_GEN_REGIONS", "us-central1,us-east4,europe-west4").split(",")
    image_model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")

    # Normalize aspect ratio and inject explicit dimension instructions
    normalized_ratio = aspect_ratio.strip() if aspect_ratio else "1:1"
    aspect_hint = {
        "1:1": "square 1:1 aspect ratio (1080x1080 pixels)",
        "4:5": "vertical portrait 4:5 aspect ratio (1080x1350 pixels)",
    }.get(normalized_ratio, f"{normalized_ratio} aspect ratio")

    prompt_with_aspect = (
        f"{image_prompt}\n\n"
        f"Format requirement: Generate this visual in high-definition {aspect_hint}."
    )

    try:
        response = _generate_with_region_failover(
            regions=regions,
            project_id=project_id,
            image_model=image_model,
            prompt_with_aspect=prompt_with_aspect,
        )

        # 1. Candidate validation
        if not response.candidates or len(response.candidates) == 0:
            return {
                "status": "error",
                "error": "Model response contained no candidates.",
            }

        candidate = response.candidates[0]

        # 2. Check safety and finish reasons
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason and str(finish_reason).upper() in (
            "SAFETY",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
            "SPII",
            "RECITATION",
        ):
            return {
                "status": "error",
                "error": f"Image generation blocked by safety filters (finish_reason: {finish_reason}).",
            }

        # 3. Extract and validate image bytes (guard against blank parts or empty data)
        if not candidate.content or not candidate.content.parts:
            return {
                "status": "error",
                "error": "Candidate content is empty or contains no parts.",
            }

        image_bytes = None
        mime_type = "image/png"

        for part in candidate.content.parts:
            if getattr(part, "inline_data", None) is not None:
                data = part.inline_data.data
                if data and len(data) > 0:
                    image_bytes = data
                    mime_type = part.inline_data.mime_type or "image/png"
                    break

        if not image_bytes or len(image_bytes) == 0:
            return {
                "status": "error",
                "error": "Model returned an empty byte stream or blank part instead of valid image data.",
            }

        # 4. Upload validated image to GCS
        ext = "jpg" if "jpeg" in mime_type else "png"

        gcs_client = storage.Client(project=project_id)
        bucket = gcs_client.bucket(bucket_name)
        blob_name = f"campaign-images/{concept_name}-{uuid.uuid4().hex[:8]}.{ext}"
        blob = bucket.blob(blob_name)
        blob.upload_from_file(io.BytesIO(image_bytes), content_type=mime_type)
        gcs_uri = f"gs://{bucket_name}/{blob_name}"

        return {
            "status": "success",
            "gcs_uri": gcs_uri,
            "concept_name": concept_name,
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Image generation failed for {concept_name}: {error_msg}")

        # Quota exhaustion across every configured region is transient --
        # flag it as `retryable` so `task_handler.py` can hand the task back
        # to Cloud Tasks (instead of acknowledging it as done) and get a
        # fresh attempt after the queue's backoff window, while still
        # completing the Firestore job document immediately below so the
        # `generate_image` caller (and the orchestrator waiting on it)
        # doesn't hang until the job-poll timeout.
        retryable = _is_quota_exhausted_error(e)

        # Fatal error classification
        lower_err = error_msg.lower()
        if "billing" in lower_err:
            error_msg = f"Fatal API Billing Error: {error_msg}"
        elif "not found" in lower_err or "404" in lower_err:
            error_msg = f"Fatal Model/Resource Not Found: {error_msg}"
        elif "permission" in lower_err or "403" in lower_err:
            error_msg = f"Fatal GCS/IAM Permission Denied: {error_msg}"

        return {
            "status": "error",
            "error": error_msg,
            "retryable": retryable,
        }
