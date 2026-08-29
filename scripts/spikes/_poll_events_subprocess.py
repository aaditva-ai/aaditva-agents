"""Standalone poller process used by `spike_events_midrun.py`.

Runs as a genuinely separate OS process (its own `vertexai.Client`, its own
credentials refresh, its own connection) so that "events are visible
mid-run" is proven across process boundaries -- exactly the broker/driver
split the real architecture depends on -- rather than an artifact of reusing
one client/session object in-process.

Usage:
    uv run scripts/spikes/_poll_events_subprocess.py <session_resource_name> <output_jsonl_path> <duration_seconds>

Writes one JSON line per poll to `output_jsonl_path`:
    {"poll_ts": "...", "elapsed_s": 12.3, "event_count": 4,
     "event_names": ["projects/.../sessions/.../events/1", ...]}
"""
from __future__ import annotations

import json
import sys
import time

import common  # noqa: E402  (resolves via the script's own directory, which
                              # Python puts first on sys.path automatically
                              # when the file is run directly)


def main() -> None:
    session_name = sys.argv[1]
    output_path = sys.argv[2]
    duration_s = float(sys.argv[3])
    poll_interval_s = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0

    client, _agent_engine, _resource_name = common.get_client()

    start = time.monotonic()
    with open(output_path, "w", encoding="utf-8") as out:
        while time.monotonic() - start < duration_s:
            poll_ts = common.utc_now_rfc3339()
            elapsed = round(time.monotonic() - start, 2)
            try:
                events = common.list_events(client, session_name)
                record = {
                    "poll_ts": poll_ts,
                    "elapsed_s": elapsed,
                    "event_count": len(events),
                    "event_names": [getattr(e, "name", None) for e in events],
                    "event_authors": [getattr(e, "author", None) for e in events],
                }
            except Exception as e:  # noqa: BLE001
                record = {"poll_ts": poll_ts, "elapsed_s": elapsed, "error": str(e)}
            out.write(json.dumps(record) + "\n")
            out.flush()
            print(f"[poller pid={__import__('os').getpid()}] t={elapsed}s -> {record}", flush=True)
            time.sleep(poll_interval_s)


if __name__ == "__main__":
    main()
