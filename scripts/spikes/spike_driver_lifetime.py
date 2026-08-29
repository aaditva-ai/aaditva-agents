"""Spike 2/4: does a single long-running `async_stream_query` drain a full
campaign to completion, and does compaction actually run afterward?

This is the shape the future `campaign-driver` service will run in:
    async for _ in engine.async_stream_query(...): pass
draining the iterator to the very end without breaking early, because ADK
only runs event compaction after all events are yielded (see
`agents/creative_director/agent.py`'s `EventsCompactionConfig`, and
`runners.py:515-519` referenced in the plan).

What this script does NOT test: whether a real Cloud Tasks HTTP-target
dispatch actually holds open for the full duration without the queue
re-dispatching. That requires the `campaign-driver` Cloud Run service and
the `campaigns` Cloud Tasks queue to exist, which is Step 2 (build) work,
not Step 1 (spike) work -- this script only proves the *application-level*
half: that draining `async_stream_query` in a plain long-lived process
completes cleanly and triggers compaction, which is the precondition for
that later infra test to even be worth running.

Usage:
    uv run scripts/spikes/spike_driver_lifetime.py [--brief-file PATH]
"""
from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from pathlib import Path

import common

SPIKE_DIR = Path(__file__).resolve().parent


async def main_async(brief: str) -> None:
    client, agent_engine, resource_name = common.get_client()
    user_id = "spike-driver-lifetime"
    session_id = str(uuid.uuid4())
    session_name = common.session_resource_name(resource_name, session_id)

    print(f"Session resource: {session_name}")
    print("Draining async_stream_query to completion (driver-style, no early break)...")

    start = time.monotonic()
    event_count = 0
    author_sequence = []
    async for event in agent_engine.async_stream_query(
        user_id=user_id, session_id=session_id, message=brief
    ):
        event_count += 1
        author = event.get("author") if isinstance(event, dict) else getattr(event, "author", None)
        author_sequence.append(author)
        if event_count % 10 == 0:
            print(f"  ...{event_count} events so far, t={round(time.monotonic() - start, 1)}s")
    total_s = round(time.monotonic() - start, 2)

    print(f"\nDrain complete: {event_count} events in {total_s}s")

    # Give the backend a moment to persist the post-run compaction event,
    # then read back the durable session to check for it.
    await asyncio.sleep(5)
    final_events = common.list_events(client, session_name)
    common.dump_json(
        SPIKE_DIR / "results" / "spike_driver_lifetime_events.json",
        [common.event_to_plain_dict(e) for e in final_events],
    )

    compaction_detected = False
    for e in final_events:
        actions = getattr(e, "actions", None)
        if actions is not None and getattr(actions, "compaction", None) is not None:
            compaction_detected = True
        raw = getattr(e, "raw_event", None) or {}
        if isinstance(raw, dict) and isinstance(raw.get("actions"), dict) and "compaction" in raw["actions"]:
            compaction_detected = True

    print("\n" + "=" * 70)
    print("RESULT: spike_driver_lifetime")
    print("=" * 70)
    print(f"Total wall-clock time to drain campaign: {total_s}s")
    print(f"Events yielded over the stream: {event_count}")
    print(f"Events persisted in the durable session: {len(final_events)}")
    print(f"Author sequence: {author_sequence}")
    print(f"Compaction event detected in the durable session: {compaction_detected}")
    if total_s > 1800:
        print(
            "==> WARNING: this run exceeded 30 minutes -- longer than the Cloud "
            "Tasks HTTP-target deadline the plan assumes. Re-check the "
            "'Cloud Run Job' alternative if real campaigns run this long."
        )
    else:
        print(
            "==> Comfortably within the planned --timeout=1800 for campaign-driver "
            "and well under the 30-minute Cloud Tasks HTTP-target ceiling."
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
