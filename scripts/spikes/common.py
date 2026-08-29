"""Shared helpers for the Step 1 architecture spikes.

These spikes exist to prove or disprove the load-bearing assumptions behind
`docs/replace-gradio-with-spa.md` (the SPA/broker/campaign-driver redesign)
*before* any of that infrastructure gets built. See each `spike_*.py` file's
module docstring for what it individually checks.

Connection pattern mirrors `run_campaign.py` / `gradio-ui/app.py`: load the
project root `.env`, connect via `vertexai.Client(...)`, and fetch the
deployed Creative Director via `client.agent_engines.get(...)`.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = Path(__file__).resolve().parent / "results"

load_dotenv(PROJECT_ROOT / ".env")


def get_project_config() -> dict[str, str]:
    project_id = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT_ID")
        or os.getenv("PROJECT_ID")
    )
    location = (
        os.getenv("CLOUD_RUN_REGION")
        or os.getenv("GCP_REGION")
        or os.getenv("LOCATION", "us-central1")
    )
    agent_engine_id = os.getenv("AGENT_ENGINE_ID")

    missing = [
        name
        for name, val in [
            ("GOOGLE_CLOUD_PROJECT", project_id),
            ("AGENT_ENGINE_ID", agent_engine_id),
        ]
        if not val
    ]
    if missing:
        print(
            f"Error: missing required .env vars: {', '.join(missing)}. "
            "Deploy the orchestrator first (uv run deploy/deploy_orchestrator.py --action deploy).",
            file=sys.stderr,
        )
        sys.exit(1)

    return {
        "project_id": project_id,
        "location": location,
        "agent_engine_id": agent_engine_id,
    }


def agent_engine_resource_name(project_id: str, location: str, agent_engine_id: str) -> str:
    if agent_engine_id.startswith("projects/"):
        return agent_engine_id
    return f"projects/{project_id}/locations/{location}/reasoningEngines/{agent_engine_id}"


def session_resource_name(agent_engine_resource: str, session_id: str) -> str:
    return f"{agent_engine_resource}/sessions/{session_id}"


def get_client():
    """Returns (client, agent_engine, resource_name) using the `vertexai.Client`
    path (the non-deprecated one), matching Key Decision #9 in the plan.
    """
    import vertexai
    from vertexai import Client

    cfg = get_project_config()
    vertexai.init(project=cfg["project_id"], location=cfg["location"])
    client = Client(project=cfg["project_id"], location=cfg["location"])
    resource_name = agent_engine_resource_name(
        cfg["project_id"], cfg["location"], cfg["agent_engine_id"]
    )
    agent_engine = client.agent_engines.get(name=resource_name)
    return client, agent_engine, resource_name


DEFAULT_CAMPAIGN_BRIEF = """
Create a complete Instagram campaign for:
- Product: EcoFlow Smart Water Bottle (tracks hydration, keeps drinks cold 24h)
- Target Audience: Health-conscious millennials, 25-35 years old
- Platform: Instagram
- Goal: Brand awareness + drive website traffic
- Brand Voice: Motivational, clean, science-backed
- Budget: $3,000
- Timeline: Launch in 2 weeks
""".strip()


def _json_default(obj: Any):
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            pass
    return str(obj)


def event_to_plain_dict(event: Any) -> dict:
    """Best-effort conversion of a `SessionEvent` pydantic model to a plain
    JSON-safe dict, keeping `raw_event` (the untyped proto-struct payload)
    alongside the typed fields so we can check whether the typed model drops
    fields (e.g. compaction metadata) that are actually present on the wire.
    """
    if hasattr(event, "model_dump"):
        try:
            return json.loads(json.dumps(event.model_dump(mode="json"), default=_json_default))
        except Exception:
            pass
    return json.loads(json.dumps(event, default=_json_default))


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=_json_default)
    print(f"Wrote {path}")


def utc_now_rfc3339() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def list_events(agent_engine_or_client, session_name: str, since_rfc3339: Optional[str] = None,
                 client: Optional[Any] = None):
    """Calls `sessions.events.list`, optionally filtered to `timestamp >= since_rfc3339`.

    `agent_engine_or_client` may be the `client` itself (has `.agent_engines.sessions`)
    or an `AgentEngine` instance — either way we go through `client.agent_engines.sessions`.
    """
    target_client = client or agent_engine_or_client
    config = None
    if since_rfc3339:
        config = {"filter": f'timestamp>="{since_rfc3339}"'}
    return list(target_client.agent_engines.sessions.events.list(name=session_name, config=config))
