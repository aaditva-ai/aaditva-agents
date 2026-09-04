"""Maps raw `sessions.events.list` events to the UI step shape the SPA
renders, replacing the fragile `startswith`/`endswith` text heuristics in
gradio-ui/app.py's `stream_chat`.

Grounded in the real event shapes captured by scripts/spikes/ against the
live Agent Engine (see scripts/spikes/README.md):

- Events expose `author`, `content.parts` (each part may carry a
  `function_call`, `function_response`, or plain `text`), `actions`, `name`
  (a full resource path ending in `.../events/{numeric_id}` -- there is no
  separate short `id` field), and `timestamp`.
- Compaction was never observed to fire in any harvested session (typed
  `actions.compaction` is not even exposed by the installed SDK; the
  `raw_event` fallback never carried it either) -- `_is_compaction_event`
  is a defensive no-op today, kept so a real compaction event would still
  be dropped rather than rendered as bogus agent output the moment one
  does appear.
- Image delivery: Step 1's spike_images confirmed `actions.artifact_delta`
  carries no bytes (`{"filename.png": 0}` -- version number only) and is a
  dead end given the creative_director's default InMemoryArtifactService.
  The viable path is the `get_image_links` function_response, whose
  `links[].url` values are already signed HTTPS URLs (the Creative
  Director calls this tool itself via SIGNING_SERVICE_ACCOUNT -- see
  agents/creative_director/get_image_links_tool.py). This normalizer
  therefore emits "image" steps from that tool response directly, rather
  than resolving artifact_delta server-side as the plan's Proposed Changes
  originally assumed; see the Step 3 entry in
  docs/replace-gradio-with-spa-job-architecture.md's Decisions section.
"""
from __future__ import annotations

import datetime
import os
import time
import urllib.request
from typing import Any

_SIGNED_URL_CACHE: dict[str, tuple[str, float]] = {}


def get_signed_url(gcs_uri: str) -> str:
    """Generate a signed GET URL for a gs:// URI, with in-memory TTL caching."""
    if not gcs_uri or not isinstance(gcs_uri, str):
        return gcs_uri or ""
    if not gcs_uri.startswith("gs://"):
        return gcs_uri

    now = time.time()
    if gcs_uri in _SIGNED_URL_CACHE:
        cached_url, expires_at = _SIGNED_URL_CACHE[gcs_uri]
        if now < expires_at:
            return cached_url

    without_prefix = gcs_uri[len("gs://"):]
    if "/" not in without_prefix:
        return gcs_uri
    bucket_name, blob_path = without_prefix.split("/", 1)
    fallback_url = f"https://storage.googleapis.com/{bucket_name}/{blob_path}"

    try:
        from google.cloud import storage
        import google.auth

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
        storage_client = storage.Client(project=project_id)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        credentials, _ = google.auth.default()

        sa_email = os.environ.get("SIGNING_SERVICE_ACCOUNT") or getattr(
            credentials, "service_account_email", None
        )

        if sa_email == "default" or (sa_email and not sa_email.endswith(".iam.gserviceaccount.com") and not sa_email.endswith(".gserviceaccount.com")):
            try:
                req = urllib.request.Request(
                    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
                    headers={"Metadata-Flavor": "Google"},
                )
                fetched_email = urllib.request.urlopen(req, timeout=1).read().decode().strip()
                if fetched_email:
                    sa_email = fetched_email
            except Exception:
                pass

        if sa_email and sa_email != "default":
            try:
                from google.auth import iam as google_auth_iam
                from google.auth.transport import requests as google_auth_requests
                from google.oauth2 import service_account as sa_module

                request = google_auth_requests.Request()
                credentials.refresh(request)

                signer = google_auth_iam.Signer(
                    request=request,
                    credentials=credentials,
                    service_account_email=sa_email,
                )
                sign_credentials = sa_module.Credentials(
                    signer=signer,
                    service_account_email=sa_email,
                    token_uri="https://oauth2.googleapis.com/token",
                )
                url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(days=7),
                    method="GET",
                    credentials=sign_credentials,
                )
                # Cache for up to 6 days
                _SIGNED_URL_CACHE[gcs_uri] = (url, now + 86400 * 6)
                return url
            except Exception:
                pass

        try:
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(days=7),
                method="GET",
            )
            _SIGNED_URL_CACHE[gcs_uri] = (url, now + 86400 * 6)
            return url
        except Exception:
            return fallback_url
    except Exception:
        return fallback_url


def _get(obj: Any, name: str, default=None):
    """Attribute access for either a pydantic model or a plain dict --
    events may arrive as either depending on caller (SDK object vs. an
    already-JSON-dumped dict), so every accessor below goes through this.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _timestamp_to_iso(value: Any) -> str | None:
    """The live SDK's `event.timestamp` is a `datetime` object, not a
    string -- confirmed against a real Agent Engine session during Step 6
    live e2e testing, which every prior test fixture (all hand-written
    with string timestamps) never exercised. broker/main.py's staleness
    logic (`_is_recent`) and the JSON response body both need a plain
    RFC3339 string, so every timestamp is normalized here, once, at the
    normalizer boundary -- rather than pushing datetime-vs-string handling
    onto every downstream consumer.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        iso = value.isoformat()
        # datetime.isoformat() renders UTC as "+00:00", not "Z" -- keep the
        # "Z" convention the rest of the codebase (and every prior test
        # fixture) already uses, since main.py's _is_recent does a literal
        # "Z" -> "+00:00" string replace that would otherwise double up.
        return iso.replace("+00:00", "Z")
    return str(value)


def _event_id(event: Any) -> str:
    """The trailing `/events/{id}` segment of `name` is the natural dedupe
    key -- stable across polls/replays and unique per event.
    """
    name = _get(event, "name") or ""
    if "/events/" in name:
        return name.rsplit("/events/", 1)[-1]
    return name or str(id(event))


def _is_compaction_event(event: Any) -> bool:
    """See module docstring: no compaction event has ever been observed on
    the wire, but this checks both the typed field (should the SDK someday
    expose it) and the untyped raw_event fallback so a real one is dropped
    rather than rendered as agent output.
    """
    actions = _get(event, "actions")
    if actions is not None and _get(actions, "compaction") is not None:
        return True
    raw = _get(event, "raw_event") or {}
    if isinstance(raw, dict):
        raw_actions = raw.get("actions") or {}
        if isinstance(raw_actions, dict) and "compaction" in raw_actions:
            return True
    return False


def _has_transfer(event: Any) -> bool:
    actions = _get(event, "actions")
    return bool(actions is not None and _get(actions, "transfer_agent"))


def _normalize_get_image_links_response(response: Any) -> list[dict]:
    """Response shape (confirmed in spike_images/spike_resume harvests):
    {"status": "success", "links": [{"title", "concept", "gcs_uri", "url"}], "signed": bool}
    """
    if not isinstance(response, dict):
        return []
    links = response.get("links") or []
    images = []
    for link in links:
        url = link.get("url")
        gcs_uri = link.get("gcs_uri")
        # Regenerate signed URL from gcs_uri when available so historical events
        # don't suffer from expired signatures after 1 hour (HTTP 400 Bad Request).
        if gcs_uri:
            fresh_url = get_signed_url(gcs_uri)
            if fresh_url and ("?" in fresh_url or not url):
                url = fresh_url
        if not url:
            continue
        images.append({"url": url, "title": link.get("title") or link.get("concept")})
    return images


def normalize_events(events: list[Any]) -> list[dict]:
    """Convert raw session events into the UI step list from the plan's
    `GET /campaigns/{sessionId}/events` contract:

        {id, author, kind, text?, toolName?, imageUrl?, timestamp}

    kind is one of: "text" | "tool_call" | "tool_result" | "image" | "transfer".
    One raw event can produce zero, one, or several steps (e.g. an event
    with two function_call parts, or a get_image_links response with three
    images, each becomes its own step so the SPA can render/dedupe at the
    same granularity it groups by).
    """
    steps: list[dict] = []

    for event in events:
        if _is_compaction_event(event):
            continue

        event_id = _event_id(event)
        author = _get(event, "author")
        timestamp = _timestamp_to_iso(_get(event, "timestamp"))
        # invocation_id groups every event from one orchestrator turn (one
        # user message through to its final response) -- Step 1's harvested
        # sessions show `author` is "creative_director" for nearly every
        # event past the first, so the SPA's step-card grouping needs
        # invocation_id alongside author or the whole transcript collapses
        # into one card (see web/src/api/selectTranscript.ts).
        invocation_id = _get(event, "invocation_id")
        content = _get(event, "content")
        parts = _get(content, "parts") or []

        part_index = 0
        for part in parts:
            function_call = _get(part, "function_call")
            function_response = _get(part, "function_response")
            text = _get(part, "text")

            if function_call is not None:
                name = _get(function_call, "name")
                if name == "display_image":
                    args = _get(function_call, "args") or {}
                    gcs_uri = _get(args, "gcs_uri") or _get(args, "gcs_url") or _get(args, "uri") or _get(args, "url")
                    concept_name = _get(args, "concept_name") or _get(args, "title") or _get(args, "name")
                    if gcs_uri:
                        signed_url = get_signed_url(gcs_uri)
                        steps.append({
                            "id": f"{event_id}:{part_index}",
                            "author": author,
                            "invocationId": invocation_id,
                            "kind": "image",
                            "toolName": name,
                            "imageUrl": signed_url,
                            "text": str(concept_name) if concept_name is not None else None,
                            "timestamp": timestamp,
                        })
                        part_index += 1
                        continue
                if name:
                    steps.append({
                        "id": f"{event_id}:{part_index}",
                        "author": author,
                        "invocationId": invocation_id,
                        "kind": "tool_call",
                        "toolName": name,
                        "timestamp": timestamp,
                    })
                    part_index += 1
                continue

            if function_response is not None:
                name = _get(function_response, "name")
                response = _get(function_response, "response")
                if name == "get_image_links":
                    for image in _normalize_get_image_links_response(response):
                        steps.append({
                            "id": f"{event_id}:{part_index}",
                            "author": author,
                            "invocationId": invocation_id,
                            "kind": "image",
                            "imageUrl": image["url"],
                            "text": image.get("title"),
                            "timestamp": timestamp,
                        })
                        part_index += 1
                elif name:
                    steps.append({
                        "id": f"{event_id}:{part_index}",
                        "author": author,
                        "invocationId": invocation_id,
                        "kind": "tool_result",
                        "toolName": name,
                        "text": _stringify_response(response),
                        "timestamp": timestamp,
                    })
                    part_index += 1
                continue

            if text:
                steps.append({
                    "id": f"{event_id}:{part_index}",
                    "author": author,
                    "invocationId": invocation_id,
                    "kind": "text",
                    "text": text,
                    "timestamp": timestamp,
                })
                part_index += 1

        if _has_transfer(event) and part_index == 0:
            # Some transfer events carry no content parts at all -- still
            # surface that a handoff happened rather than dropping the
            # event silently.
            steps.append({
                "id": f"{event_id}:transfer",
                "author": author,
                "invocationId": invocation_id,
                "kind": "transfer",
                "timestamp": timestamp,
            })

    return steps


def _stringify_response(response: Any) -> str:
    """Tool responses are already-parsed dicts (e.g. {"result": "..."} for
    specialist calls, {"status": "success", ...} for display_image) --
    render the human-readable `result` field when present, otherwise fall
    back to the raw dict so nothing is silently lost.
    """
    if isinstance(response, dict) and "result" in response:
        return str(response["result"])
    return str(response)


def dedupe_by_id(steps: list[dict]) -> list[dict]:
    """Idempotent replay guard for cursor pages that may overlap slightly at
    the boundary -- keeps first occurrence, preserves order.
    """
    seen: set[str] = set()
    deduped = []
    for step in steps:
        if step["id"] in seen:
            continue
        seen.add(step["id"])
        deduped.append(step)
    return deduped
