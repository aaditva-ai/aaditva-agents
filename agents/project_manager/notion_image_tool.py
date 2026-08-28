"""
Notion Image Embedding Tool

Embeds campaign images directly into Notion project pages using the Notion Direct Upload API,
falling back gracefully to Notion-hosted external image blocks or titled Markdown links.
"""

import io
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger("ai_creative_studio.project_manager.notion_images")


def _make_notion_request(
    endpoint: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    data: Optional[bytes | dict] = None,
    timeout: int = 30,
) -> tuple[int, dict | str]:
    """Execute an HTTP request to the Notion API with retries on 429/5xx."""
    token = os.environ.get("NOTION_TOKEN", "")
    version = os.environ.get("NOTION_API_VERSION", "2022-06-28")

    req_headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": version,
    }
    if headers:
        req_headers.update(headers)

    body_bytes = None
    if isinstance(data, dict):
        body_bytes = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    elif isinstance(data, bytes):
        body_bytes = data

    url = endpoint if endpoint.startswith("http") else f"https://api.notion.com/v1/{endpoint.lstrip('/')}"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.status
                raw_body = resp.read().decode("utf-8")
                try:
                    return status_code, json.loads(raw_body)
                except Exception:
                    return status_code, raw_body
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            try:
                return e.code, json.loads(err_body)
            except Exception:
                return e.code, err_body
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return 500, {"error": str(e)}

    return 500, {"error": "Request timed out after retries"}


def _download_gcs_blob(gcs_uri: str) -> tuple[bytes | None, str]:
    """Download image bytes from GCS bucket URI."""
    try:
        from google.cloud import storage

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
        client = storage.Client(project=project_id)

        clean_uri = gcs_uri.strip()
        if not clean_uri.startswith("gs://"):
            return None, "Invalid GCS URI"

        without_prefix = clean_uri[len("gs://"):]
        bucket_name, blob_path = without_prefix.split("/", 1)

        blob = client.bucket(bucket_name).blob(blob_path)
        content_bytes = blob.download_as_bytes()

        ext = blob_path.rsplit(".", 1)[-1].lower() if "." in blob_path else "png"
        mime_type = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"

        return content_bytes, mime_type
    except Exception as e:
        logger.warning(f"Could not download blob from {gcs_uri}: {e}")
        return None, str(e)


def attach_campaign_images(page_id: str, images: list[dict]) -> dict:
    """
    Attach campaign images to a Notion project page.

    Args:
        page_id: UUID of the Notion project page.
        images: List of image dictionaries, each containing:
                - "title": Presentation title (e.g. "Post 1 — Sunrise Yoga Flow")
                - "gcs_uri": Optional gs:// URI to download bytes from GCS
                - "url": Optional HTTPS signed URL

    Returns:
        {"status": "success"|"partial"|"error", "embedded": int, "linked": int, "failed": list}
    """
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        return {
            "status": "error",
            "error": "NOTION_TOKEN is not configured in environment.",
            "embedded": 0,
            "linked": 0,
        }

    clean_page_id = page_id.replace("-", "").strip()
    if not clean_page_id:
        return {
            "status": "error",
            "error": "Invalid or empty page_id provided.",
            "embedded": 0,
            "linked": 0,
        }

    embedded_count = 0
    linked_count = 0
    failed_images = []
    child_blocks = []

    # Section heading block
    child_blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "Generated Campaign Visuals"},
                }
            ]
        },
    })

    for img in images:
        title = img.get("title") or img.get("concept") or "Campaign Visual"
        gcs_uri = img.get("gcs_uri", "")
        signed_url = img.get("url", "")

        block_added = False

        # Tier 1: Try Direct Upload if GCS URI is present
        if gcs_uri:
            image_bytes, mime_type = _download_gcs_blob(gcs_uri)
            if image_bytes:
                filename = gcs_uri.rsplit("/", 1)[-1]
                # Initiate file upload with Notion
                status, resp = _make_notion_request(
                    "file_uploads",
                    method="POST",
                    data={
                        "mode": "single_part",
                        "filename": filename,
                        "content_type": mime_type,
                    },
                )

                if status in (200, 201) and isinstance(resp, dict) and "id" in resp:
                    upload_id = resp["id"]
                    # Send bytes via file_uploads/{id}/send
                    # Multipart upload
                    boundary = "----NotionUploadBoundary7MA4YWxkTrZu0gW"
                    body = (
                        f"--{boundary}\r\n"
                        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                        f"Content-Type: {mime_type}\r\n\r\n"
                    ).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

                    send_status, _ = _make_notion_request(
                        f"file_uploads/{upload_id}/send",
                        method="POST",
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                        data=body,
                    )

                    if send_status in (200, 201, 204):
                        child_blocks.append({
                            "object": "block",
                            "type": "image",
                            "image": {
                                "type": "file_upload",
                                "file_upload": {"id": upload_id},
                                "caption": [{"type": "text", "text": {"content": title}}],
                            },
                        })
                        embedded_count += 1
                        block_added = True

        # Tier 2: External Image block if signed_url is available
        if not block_added and signed_url:
            child_blocks.append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": signed_url},
                    "caption": [{"type": "text", "text": {"content": title}}],
                },
            })
            embedded_count += 1
            block_added = True

        # Tier 3: Titled link fallback (never bare raw signed URL)
        if not block_added and signed_url:
            child_blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"📸 {title}",
                                "link": {"url": signed_url},
                            },
                        }
                    ]
                },
            })
            linked_count += 1
            block_added = True

        if not block_added:
            failed_images.append(title)

    # Append all blocks to the page in one call
    if len(child_blocks) > 1:
        append_status, append_resp = _make_notion_request(
            f"blocks/{clean_page_id}/children",
            method="PATCH",
            data={"children": child_blocks},
        )

        if append_status not in (200, 201):
            logger.error(f"Failed to append blocks to Notion page {page_id}: {append_resp}")
            return {
                "status": "error",
                "error": f"Failed to append image blocks: {append_resp}",
                "embedded": 0,
                "linked": 0,
                "failed": [img.get("title", "") for img in images],
            }

    return {
        "status": "success" if not failed_images else "partial",
        "embedded": embedded_count,
        "linked": linked_count,
        "failed": failed_images,
    }
