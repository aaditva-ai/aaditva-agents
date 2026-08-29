# Step 1 spikes — proving the SPA/broker/campaign-driver assumptions

See `docs/replace-gradio-with-spa.md` for the full plan. These four scripts
exist to verify the plan's load-bearing assumptions against the **live**
Agent Engine deployment before any of Steps 2–7 (campaign-driver, broker,
SPA) get built. Each script is self-contained, requires only `.env` to be
populated (`GOOGLE_CLOUD_PROJECT`, `AGENT_ENGINE_ID`, etc. — same as
`run_campaign.py`), and writes its findings to `results/*.json` plus a
human-readable verdict printed at the end of the run.

Run them with `uv run` from the project root, exactly like the existing
`run_campaign.py` and `deploy/*.py` scripts, so they use the project's own
locked dependency set rather than an ad hoc environment:

```bash
uv run scripts/spikes/spike_events_midrun.py     # ~7-10 min (one campaign)
uv run scripts/spikes/spike_driver_lifetime.py   # ~7-10 min (one campaign)
uv run scripts/spikes/spike_resume.py            # ~2-3 min
uv run scripts/spikes/spike_images.py            # ~7-10 min (one campaign)
```

Each incurs the cost of at least one real campaign run (Gemini + image
generation calls), so budget for that before running all four back to back.

## What each one checks

| Script | Question | Plan reference |
|---|---|---|
| `spike_events_midrun.py` | Do `sessions.events.list` reads from a **separate process** see events **while the campaign is still running**, or only after it finishes? | Risk table: "Events may not be visible mid-invocation — the load-bearing assumption of the whole architecture." |
| `spike_driver_lifetime.py` | Does draining `async_stream_query` to completion (no early break) run cleanly for a full ~7min campaign, and does event compaction actually fire afterward? | Step 1 bullet 3; `runners.py:515-519` compaction-after-full-drain requirement. |
| `spike_resume.py` | If a driver crashes mid-campaign, does re-invoking on the same `session_id` continue from where it left off, or does the Creative Director redo already-completed specialist calls? | Risk table: "Resume may restart rather than continue the campaign." |
| `spike_images.py` | Which of the two candidate image-delivery paths actually works from a separate process: ADK `artifact_delta` (Path A) or the existing `get_image_links` tool's signed HTTPS URLs (Path B)? | Contributing defect #1; Risk table: "`display_image` artifacts carry no bytes over streamQuery." |

`common.py` holds the shared connection/session-naming helpers (mirrors the
`vertexai.Client` + `client.agent_engines.get(...)` pattern already used in
`run_campaign.py`). `_poll_events_subprocess.py` is not a spike itself — it's
the child-process poller `spike_events_midrun.py` spawns so that "a separate
process can see events mid-run" is actually tested across a process
boundary, not just faked with two in-process coroutines.

## Findings so far

Record the verdict of each run here once executed, so Step 2 onward can
cite this instead of re-deriving it:

- `spike_events_midrun`: **CONFIRMED — load-bearing assumption holds.** A
  separate `_poll_events_subprocess.py` process saw the first
  `creative_director` event at t≈26–35s into the run while the full campaign
  ran 550–600s+. Verified across two independent real campaigns (sessions
  `4c6db47c…` and `82b15812…`). Note: the script itself did not exit cleanly
  both times — see the 503 note below — so this verdict comes from
  re-reading `sessions.events.list` directly rather than the script's own
  printed summary; `results/spike_events_midrun_*` were not produced by a
  clean run.
- `spike_driver_lifetime`: **CONFIRMED — clean full drain, well within
  budget; compaction does NOT fire.** Ran cleanly end-to-end with no early
  break and no 503 this time: 31 events streamed / 32 persisted in 489.35s
  (session `470b8acc…`), comfortably inside `--timeout=1800`. But 5s after
  the full drain, `sessions.events.list` showed **no compaction event** —
  neither the typed `actions.compaction` field nor the `raw_event`
  fallback — matching every other harvested session in this round,
  including the 34-event fully-completed one from the resume spike. See
  the compaction note below: this is now a repeated null result across 4
  independent sessions, not just one under-length run.
- `spike_resume`: **CONFIRMED — the orchestrator continues, it does not
  restart.** Cancelled the stream immediately after `brand_strategist`
  returned (t=130s); re-invoking on the same `session_id` with a "continue"
  instruction picked up with `copywriter` next — the specialist that
  hadn't run yet — with no repeated specialist calls. That same re-invoked
  session then went on to run `designer` → `display_image` (×6 across
  revisions) → `critic` → `designer` → `display_image` → `get_image_links` →
  `project_manager` → a final summary, entirely without any client attached
  after the initial cancel (session `9d68b0f4…`, 34 events). No "do not
  redo completed steps" prompt change appears necessary.
- `spike_images`: **CONFIRMED — Path B is the answer, build on it.** The
  `get_image_links` function_response (from the same `9d68b0f4…` session)
  returned 3 signed `storage.googleapis.com` URLs; all 3 independently
  fetched `200 image/png`. Path A (`actions.artifact_delta`) does appear on
  the wire (`{"filename.png": 0}` shape — version number only, no bytes,
  confirming the concern below), so `events_normalizer.py` should key image
  rendering off the `get_image_links` tool response, not `artifact_delta`.

### The recurring 503 (new finding, not anticipated by the plan)

Every real campaign run against the live Agent Engine in this round (3 of 3)
hit a `google.genai.errors.ServerError: 503 UNAVAILABLE` from
`async_stream_query` roughly 9–10 minutes in, consistently around the
designer/critic/image-generation stage — never at the very start. This
crashed the *client-side* spike scripts every time, but in every case the
session kept executing and accumulating events on the server afterward (one
session went on to fully complete the campaign with zero client attached).
This is strong additional evidence for Key Decision #1 (session-side
execution is decoupled from the client connection) but it also means:

- `campaign-driver`'s `POST /drive` handler must not treat a mid-drain
  `ServerError`/503 from `async_stream_query` as fatal in a way that marks
  the campaign document `failed` if the session is, in fact, still running
  or already complete server-side — it should re-read `sessions.events.list`
  before writing a terminal status, or retry the drain loop rather than
  giving up on the first stream error.
- This flakiness is orthogonal to anything in our code (it reproduced
  identically across `spike_events_midrun`, `spike_resume` phase 2, and is
  worth watching for in `spike_driver_lifetime` too) and should be treated
  as an expected transient condition to design around in Step 2, not a bug
  to fix here.

### Compaction: resolved as a non-issue for now

Across all 4 harvested sessions in this round — including two that ran a
full campaign to natural completion (`9d68b0f4…` at 34 events/18 tool calls,
and the dedicated `spike_driver_lifetime` run at `470b8acc…`, 32 events) —
**no event ever showed `actions.compaction` set**, on the typed field or in
`raw_event`. This is a consistent null result, not a fluke of one short run.

Two plausible explanations, either of which is fine for Step 3:
1. The `EventsCompactionConfig` threshold
   (`agents/creative_director/agent.py:134-143`) is tuned for much longer/
   larger sessions than a single ~8-minute, ~30-event campaign produces, so
   compaction simply never triggers at this scale in practice.
2. Compaction summaries surface as an ordinary `creative_director`-authored
   text event rather than via a distinguishing `actions` field, and would
   need to be identified by content shape instead.

Either way, `events_normalizer.py` does not need special-case compaction
filtering to ship Step 3 correctly for campaigns of this size — there is
nothing to filter yet. Revisit if/when a campaign is observed to actually
grow large enough to trigger it (or if raw session dumps ever show a
compaction-shaped event by content instead of by `actions` field).

Note from reading the installed SDK (`google-cloud-aiplatform==1.164.0`,
pinned in `uv.lock`) ahead of running these: the typed `SessionEvent.actions`
model returned by `sessions.events.list` does **not** expose a `compaction`
field at all (only `artifact_delta`, `escalate`, `requested_auth_configs`,
`skip_summarization`, `state_delta`, `transfer_agent` — see
`vertexai/_genai/types/common.py`), even though the raw ADK `Event.actions`
object does. Every script here checks both the typed field and the
untyped `raw_event` fallback so we know definitively whether compaction
metadata survives onto the wire at all, or whether `events_normalizer.py`
will have to detect compaction summaries some other way (e.g. by author or
by content shape) in Step 3.

Separately: `agents/creative_director/agent.py`'s `App(...)` does not pass
an `artifact_service_builder`, so ADK defaults to `InMemoryArtifactService()`
— not durable and not reachable from a different process/service. That
makes Path A (`artifact_delta`) a structurally weak foundation for the
broker regardless of what `spike_images.py` reports, since even if the
delta is visible, the bytes behind it may not be recoverable from the
broker's own process. `agents/creative_director/prompt.py` already
instructs the Creative Director to call `get_image_links` near the end of
every campaign, which produces signed HTTPS URLs via GCS directly — with no
dependency on the ADK artifact system. `spike_images.py` checks both.
