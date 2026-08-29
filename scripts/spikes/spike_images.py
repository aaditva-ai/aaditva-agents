"""Spike 4/4: how do generated images actually reach a client in remote mode?

Contributing defect #1 in the diagnosis: remote mode only handles inline
`inline_data` parts, but `streamQuery`/`async_stream_query` only emits
`actions.artifact_delta` for artifacts saved via `display_image`'s
`tool_context.save_artifact(...)` -- and `artifact_delta` carries no bytes,
only `{filename: version}`.

This script checks BOTH candidate paths empirically instead of assuming the
plan's stated mitigation ("the broker reads artifacts server-side and signs
URLs") is even viable:

  Path A -- ADK artifact service: `display_image_tool.py` saves to whatever
  `artifact_service` the `App(...)` in `agents/creative_director/agent.py`
  is configured with. That `App(...)` call does NOT pass an
  `artifact_service_builder`, so ADK defaults to `InMemoryArtifactService()`
  -- which is NOT durable or reachable from a different process (e.g. the
  broker, running as a separate Cloud Run service). If that's confirmed,
  `actions.artifact_delta` may appear in the event stream/session but the
  bytes behind it are unrecoverable after the fact, and Path A is a dead
  end for this architecture regardless of transport.

  Path B -- `get_image_links` tool: `agents/creative_director/prompt.py`
  already instructs the Creative Director to call `get_image_links(...)`
  near the end of every campaign with all approved `gcs_uri` values, which
  independently generates signed HTTPS URLs via the same
  `SIGNING_SERVICE_ACCOUNT` / IAM SignBlob path the plan wants the broker to
  reuse -- with NO dependency on the ADK artifact system at all. If the
  resulting `function_response` event carries fetchable URLs, that is
  almost certainly the real path to use in `events_normalizer.py`, and
  fixing image rendering may be as simple as surfacing that one tool's
  response instead of touching `artifact_delta`/GCS-signing code at all.

Usage:
    uv run scripts/spikes/spike_images.py [--brief-file PATH]
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

import requests

import common

SPIKE_DIR = Path(__file__).resolve().parent


async def main_async(brief: str) -> None:
    client, agent_engine, resource_name = common.get_client()
    user_id = "spike-images"
    session_id = str(uuid.uuid4())
    session_name = common.session_resource_name(resource_name, session_id)

    print(f"Session resource: {session_name}")
    print("Running a campaign to completion so it reaches display_image + get_image_links...")

    async for event in agent_engine.async_stream_query(
        user_id=user_id, session_id=session_id, message=brief
    ):
        author = event.get("author") if isinstance(event, dict) else getattr(event, "author", None)
        if author:
            print(f"  ...{author}", end=" ", flush=True)
    print()

    await asyncio.sleep(3)
    final_events = common.list_events(client, session_name)
    common.dump_json(
        SPIKE_DIR / "results" / "spike_images_events.json",
        [common.event_to_plain_dict(e) for e in final_events],
    )

    artifact_delta_events = []
    get_image_links_responses = []
    gcs_uris_seen = set()

    for e in final_events:
        actions = getattr(e, "actions", None)
        if actions is not None and getattr(actions, "artifact_delta", None):
            artifact_delta_events.append(actions.artifact_delta)

        content = getattr(e, "content", None)
        parts = getattr(content, "parts", None) or []
        for p in parts:
            fr = getattr(p, "function_response", None)
            if fr is not None and getattr(fr, "name", None) == "get_image_links":
                get_image_links_responses.append(fr.response)
            text = getattr(p, "text", None)
            if text:
                for token in text.split():
                    if token.startswith("gs://"):
                        gcs_uris_seen.add(token.rstrip(".,)"))

    print("\n" + "=" * 70)
    print("RESULT: spike_images")
    print("=" * 70)
    print(f"Events with actions.artifact_delta set (Path A): {len(artifact_delta_events)}")
    for d in artifact_delta_events:
        print(f"   artifact_delta: {d}")
    print(f"get_image_links function_response events found (Path B): {len(get_image_links_responses)}")

    fetchable = 0
    total_urls = 0
    for resp in get_image_links_responses:
        links = (resp or {}).get("links", [])
        for link in links:
            total_urls += 1
            url = link.get("url")
            title = link.get("title")
            if not url:
                continue
            try:
                r = requests.get(url, timeout=10, stream=True)
                ok = r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/")
                print(f"   [{ 'OK' if ok else f'HTTP {r.status_code}' }] {title}: {url[:100]}...")
                if ok:
                    fetchable += 1
            except Exception as exc:  # noqa: BLE001
                print(f"   [ERROR fetching] {title}: {exc}")

    print(f"\nRaw gs:// URIs seen anywhere in event text: {len(gcs_uris_seen)}")

    print("\n" + "-" * 70)
    if artifact_delta_events and not get_image_links_responses:
        print(
            "==> Only Path A (artifact_delta) fired. Confirm whether the bytes "
            "are actually retrievable from a separate broker process before "
            "committing to the artifact_delta-signing approach."
        )
    elif get_image_links_responses and total_urls and fetchable == total_urls:
        print(
            "==> Path B (get_image_links) works end-to-end: every signed URL "
            "returned by the tool was independently fetchable as an image. "
            "Recommend building events_normalizer.py's image handling around "
            "the get_image_links function_response instead of artifact_delta "
            "-- it needs no ADK artifact service at all, sidestepping the "
            "InMemoryArtifactService durability problem entirely."
        )
    elif get_image_links_responses and fetchable < total_urls:
        print(
            f"==> Path B fired but only {fetchable}/{total_urls} URLs were "
            "fetchable -- investigate signing/expiry before relying on it."
        )
    else:
        print(
            "==> Neither path produced usable image references in this run. "
            "Re-run with a brief that reliably reaches the Designer step, or "
            "inspect results/spike_images_events.json for what the Creative "
            "Director actually did."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief-file", type=str, default=None)
    args = parser.parse_args()
    brief = common.DEFAULT_CAMPAIGN_BRIEF
    if args.brief_file:
        brief = Path(args.brief_file).read_text(encoding="utf-8").strip()
    asyncio.run(main_async(brief))


if __name__ == "__main__":
    main()
