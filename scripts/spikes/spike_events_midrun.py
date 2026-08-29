"""Spike 1/4: the single load-bearing assumption of the whole redesign.

Question: does `sessions.events.list` (the durable Agent Engine session
store) surface events *while a campaign is still in flight*, and from a
genuinely separate process/connection -- not just after the run finishes?

If events only appear post-completion, the "session events are the single
source of truth" architecture (Key Decision #1 in the plan) collapses back
to Gradio's problem: the UI would still have nothing to poll until the
whole campaign is done. In that case the plan's own fallback applies: the
driver publishes incremental progress into the Firestore campaign document
instead, and the SPA/broker contracts stay the same.

What this script does:
  1. Starts a campaign via `async_stream_query` in *this* process, recording
     the wall-clock time each event arrives over the stream.
  2. Concurrently spawns `_poll_events_subprocess.py` as a real child
     process with its own client/session, polling `sessions.events.list`
     every 2s for the duration of the run.
  3. After the run completes, cross-references the two timelines and
     reports whether the poller ever saw events before the stream finished.
  4. Dumps every raw event (including `raw_event`, the untyped proto-struct
     payload) to `results/spike_events_midrun_events.json` so a human/LLM
     can inspect: are compaction summary events distinguishable, does
     `actions.artifact_delta` appear, does the `get_image_links` tool
     response show up with a plain HTTPS URL.

Usage:
    uv run scripts/spikes/spike_events_midrun.py [--brief-file PATH]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import common

SPIKE_DIR = Path(__file__).resolve().parent


async def run_campaign_and_record(agent_engine, user_id: str, session_id: str, brief: str):
    """Drains `async_stream_query`, recording (monotonic_elapsed, event) pairs."""
    start = time.monotonic()
    stream_events = []
    async for event in agent_engine.async_stream_query(
        user_id=user_id, session_id=session_id, message=brief
    ):
        elapsed = round(time.monotonic() - start, 2)
        author = event.get("author") if isinstance(event, dict) else getattr(event, "author", None)
        stream_events.append({"elapsed_s": elapsed, "author": author, "raw": event})
        print(f"[stream] t={elapsed}s author={author}", flush=True)
    total = round(time.monotonic() - start, 2)
    return stream_events, total


async def main_async(brief: str) -> None:
    client, agent_engine, resource_name = common.get_client()
    user_id = "spike-events-midrun"
    session_id = str(uuid.uuid4())
    session_name = common.session_resource_name(resource_name, session_id)

    print(f"Session resource: {session_name}")

    poll_output = SPIKE_DIR / "results" / "spike_events_midrun_polls.jsonl"
    poll_output.parent.mkdir(parents=True, exist_ok=True)
    if poll_output.exists():
        poll_output.unlink()

    # Generous upper bound; the poller subprocess exits on its own timer
    # regardless of when the campaign actually finishes.
    poller_duration_s = 900
    poller = subprocess.Popen(
        [
            sys.executable,
            str(SPIKE_DIR / "_poll_events_subprocess.py"),
            session_name,
            str(poll_output),
            str(poller_duration_s),
            "2",
        ]
    )
    print(f"Spawned poller subprocess pid={poller.pid}")

    try:
        stream_events, total_s = await run_campaign_and_record(
            agent_engine, user_id, session_id, brief
        )
    finally:
        time.sleep(3)  # let the poller take one more sample after completion
        poller.terminate()
        try:
            poller.wait(timeout=10)
        except subprocess.TimeoutExpired:
            poller.kill()

    # Final full dump of every event via sessions.events.list, for manual
    # inspection of compaction / artifact_delta / get_image_links shapes.
    final_events = common.list_events(client, session_name)
    common.dump_json(
        SPIKE_DIR / "results" / "spike_events_midrun_events.json",
        [common.event_to_plain_dict(e) for e in final_events],
    )
    common.dump_json(
        SPIKE_DIR / "results" / "spike_events_midrun_stream.json",
        stream_events,
    )

    # Cross-reference: did the poller see any events before the stream
    # reported completion?
    poll_records = []
    if poll_output.exists():
        with open(poll_output, encoding="utf-8") as f:
            poll_records = [json.loads(line) for line in f if line.strip()]

    first_nonzero_poll = next((r for r in poll_records if r.get("event_count", 0) > 0), None)

    print("\n" + "=" * 70)
    print("RESULT: spike_events_midrun")
    print("=" * 70)
    print(f"Session: {session_name}")
    print(f"Total campaign wall-clock time: {total_s}s")
    print(f"Events emitted over the stream: {len(stream_events)}")
    print(f"Events in final sessions.events.list read: {len(final_events)}")
    print(f"Poll samples recorded (separate process): {len(poll_records)}")
    if first_nonzero_poll:
        print(
            f"First poll to see events: t={first_nonzero_poll['elapsed_s']}s "
            f"with {first_nonzero_poll['event_count']} event(s) "
            f"(campaign total was {total_s}s)"
        )
        if first_nonzero_poll["elapsed_s"] < total_s - 5:
            print(
                "==> LOAD-BEARING ASSUMPTION HOLDS: a separate process saw session "
                "events well before the campaign finished streaming."
            )
        else:
            print(
                "==> INCONCLUSIVE/NEGATIVE: the separate process only saw events "
                "near/after completion. Re-check with a longer campaign or shorter "
                "poll interval before trusting the architecture on this point."
            )
    else:
        print(
            "==> LOAD-BEARING ASSUMPTION FAILS: the poller never saw any events "
            "during the whole run. Session events are NOT visible mid-invocation "
            "-- fall back to the Firestore-progress-document design instead."
        )

    # Compaction-field visibility check (see plan risk #2 and this file's
    # module docstring): does the typed SDK model expose `actions.compaction`,
    # or only `raw_event`?
    compaction_hits_typed = 0
    compaction_hits_raw = 0
    artifact_delta_hits = 0
    get_image_links_hits = 0
    for e in final_events:
        actions = getattr(e, "actions", None)
        if actions is not None and getattr(actions, "compaction", None) is not None:
            compaction_hits_typed += 1
        raw = getattr(e, "raw_event", None) or {}
        if isinstance(raw, dict):
            raw_actions = raw.get("actions") or {}
            if isinstance(raw_actions, dict) and "compaction" in raw_actions:
                compaction_hits_raw += 1
        if actions is not None and getattr(actions, "artifact_delta", None):
            artifact_delta_hits += 1
        content = getattr(e, "content", None)
        parts = getattr(content, "parts", None) or []
        for p in parts:
            fr = getattr(p, "function_response", None)
            if fr is not None and getattr(fr, "name", None) == "get_image_links":
                get_image_links_hits += 1

    print(f"\nEvents with typed actions.compaction set: {compaction_hits_typed}")
    print(f"Events with raw_event['actions']['compaction'] key present: {compaction_hits_raw}")
    print(f"Events with actions.artifact_delta set: {artifact_delta_hits}")
    print(f"Events containing a get_image_links function_response: {get_image_links_hits}")
    print(
        "\nSee results/spike_events_midrun_events.json for the full raw dump "
        "(needed by Step 3's events_normalizer.py to decide the actual "
        "compaction-filtering and image-URL-extraction logic)."
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
