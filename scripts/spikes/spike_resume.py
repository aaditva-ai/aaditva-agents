"""Spike 3/4: if a driver crashes mid-campaign, does re-invoking on the same
session_id continue the campaign, or does the Creative Director restart it
from scratch (re-running specialists it already called)?

This determines whether `agents/creative_director/prompt.py` needs a "do
not redo completed steps" instruction (Risk table + Step 6 in the plan)
before `useResumeCampaign` can be trusted.

What this script does:
  1. Starts a campaign via `async_stream_query` and cancels the asyncio task
     partway through (simulating a driver crash) -- deliberately *before*
     the run finishes, once at least one specialist has been called.
  2. Re-invokes `async_stream_query` on the SAME session_id with a short
     "continue" instruction, appended to the same session history the ADK
     runner already persisted.
  3. Diffs the specialist-call sequence before vs. after the interruption:
     if the same specialist (e.g. brand_strategist) gets called again with
     a similar prompt, that's a restart; if the sequence picks up with a
     specialist that hadn't run yet, that's a continuation.

This is inherently a bit fuzzy (an LLM orchestrator, not a state machine),
so the script prints the full before/after tool-call sequence and leaves
the final call to a human/LLM reading the transcript rather than asserting
a boolean verdict.

Usage:
    uv run scripts/spikes/spike_resume.py [--cancel-after-seconds N]
"""
from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from pathlib import Path

import common

SPIKE_DIR = Path(__file__).resolve().parent


def _extract_tool_calls(event) -> list[str]:
    names = []
    content = event.get("content") if isinstance(event, dict) else None
    parts = (content or {}).get("parts", []) if isinstance(content, dict) else []
    for p in parts:
        fc = p.get("functionCall") or p.get("function_call")
        if fc and fc.get("name"):
            names.append(fc["name"])
    return names


async def drain_until_cancelled(agent_engine, user_id, session_id, message, cancel_after_s):
    events = []
    start = time.monotonic()

    async def _consume():
        async for event in agent_engine.async_stream_query(
            user_id=user_id, session_id=session_id, message=message
        ):
            events.append(event)
            names = _extract_tool_calls(event)
            if names:
                print(f"  [t={round(time.monotonic() - start, 1)}s] tool_call(s): {names}")

    task = asyncio.create_task(_consume())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=cancel_after_s)
        print("  (campaign finished naturally before the cancel deadline)")
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        print(f"  --> cancelled the stream at t={cancel_after_s}s (simulated driver crash)")
    return events


async def main_async(cancel_after_s: float) -> None:
    client, agent_engine, resource_name = common.get_client()
    user_id = "spike-resume"
    session_id = str(uuid.uuid4())
    session_name = common.session_resource_name(resource_name, session_id)

    print(f"Session resource: {session_name}")
    print(f"Phase 1: starting campaign, will simulate a crash at t={cancel_after_s}s...")
    phase1_events = await drain_until_cancelled(
        agent_engine, user_id, session_id, common.DEFAULT_CAMPAIGN_BRIEF, cancel_after_s
    )
    phase1_tool_calls = [n for e in phase1_events for n in _extract_tool_calls(e)]

    # Let any in-flight writes settle before reading the durable session.
    await asyncio.sleep(3)
    mid_events = common.list_events(client, session_name)
    print(f"\nAfter the simulated crash, durable session has {len(mid_events)} event(s).")

    print("\nPhase 2: re-invoking on the SAME session_id with a 'continue' instruction...")
    continue_message = (
        "Continue the campaign from where you left off. Do not repeat any "
        "specialist calls that already returned a result above -- pick up "
        "with the next step."
    )
    phase2_events = []
    async for event in agent_engine.async_stream_query(
        user_id=user_id, session_id=session_id, message=continue_message
    ):
        phase2_events.append(event)
        names = _extract_tool_calls(event)
        if names:
            print(f"  [phase 2] tool_call(s): {names}")

    phase2_tool_calls = [n for e in phase2_events for n in _extract_tool_calls(e)]

    final_events = common.list_events(client, session_name)
    common.dump_json(
        SPIKE_DIR / "results" / "spike_resume_events.json",
        [common.event_to_plain_dict(e) for e in final_events],
    )

    print("\n" + "=" * 70)
    print("RESULT: spike_resume")
    print("=" * 70)
    print(f"Specialists called before the simulated crash: {phase1_tool_calls}")
    print(f"Specialists called after re-invoking 'continue': {phase2_tool_calls}")
    repeated = set(phase1_tool_calls) & set(phase2_tool_calls)
    if repeated:
        print(
            f"==> Overlap detected: {repeated} were called again after resume. "
            "This suggests the orchestrator RESTARTS rather than continues -- "
            "add a 'do not redo completed steps' instruction to "
            "agents/creative_director/prompt.py per the plan's Risk table."
        )
    else:
        print(
            "==> No repeated specialist calls detected -- the orchestrator "
            "appears to continue from session history rather than restart. "
            "Re-read results/spike_resume_events.json to confirm the visible "
            "text also reads as a continuation, not just non-overlapping "
            "tool names."
        )
    print(
        f"\nFull event dump: results/spike_resume_events.json "
        f"({len(final_events)} events total across both phases)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cancel-after-seconds",
        type=float,
        default=60.0,
        help="How long to let the campaign run before simulating a driver crash.",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.cancel_after_seconds))


if __name__ == "__main__":
    main()
