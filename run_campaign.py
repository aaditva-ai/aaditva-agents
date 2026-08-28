"""
Run a campaign through the deployed Creative Director on Agent Engine.
Usage:
    uv run run_campaign.py
    uv run run_campaign.py --prompt "Create an Instagram campaign for..."
    uv run run_campaign.py --prompt-file docs/demo/briefs/revision-trigger.txt
"""

import argparse
import os
import sys

import vertexai
from dotenv import load_dotenv
from vertexai import Client

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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run an end-to-end creative campaign via deployed Agent Engine."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-p", "--prompt",
        type=str,
        help="Inline campaign brief to run."
    )
    group.add_argument(
        "-f", "--prompt-file",
        type=str,
        help="Path to a text file containing the campaign brief."
    )
    parser.add_argument(
        "-u", "--user-id",
        type=str,
        default="workshop-user",
        help="User ID for the Agent Engine session (default: workshop-user)."
    )
    parser.add_argument(
        "-s", "--session-id",
        type=str,
        default=None,
        help="Optional existing session ID to continue."
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress session info banner."
    )
    return parser.parse_args()


def resolve_brief(args) -> str:
    if args.prompt:
        return args.prompt.strip()
    if args.prompt_file:
        if not os.path.isfile(args.prompt_file):
            print(f"Error: Prompt file not found: {args.prompt_file}", file=sys.stderr)
            sys.exit(1)
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    return DEFAULT_CAMPAIGN_BRIEF


def main():
    load_dotenv()
    args = parse_args()

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

    if not project_id:
        print(
            "Error: Google Cloud project ID not set. Ensure GOOGLE_CLOUD_PROJECT is defined in .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not agent_engine_id:
        print(
            "Error: AGENT_ENGINE_ID is not set in .env. Run `uv run deploy/deploy_orchestrator.py --action deploy` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    brief = resolve_brief(args)

    vertexai.init(project=project_id, location=location)
    client = Client(project=project_id, location=location)

    resource_name = (
        f"projects/{project_id}/locations/{location}/"
        f"reasoningEngines/{agent_engine_id}"
    )

    try:
        agent_engine = client.agent_engines.get(name=resource_name)
    except Exception as e:
        print(f"Error connecting to Agent Engine ({resource_name}): {e}", file=sys.stderr)
        sys.exit(1)

    session_id = args.session_id
    if not session_id:
        session = agent_engine.create_session(user_id=args.user_id)
        session_id = session["id"]

    if not args.quiet:
        print(f"Agent Engine: {agent_engine_id}")
        print(f"Session ID:   {session_id}")
        print(f"User ID:      {args.user_id}")
        print("=" * 60)
        print("Brief:")
        print(brief)
        print("=" * 60 + "\n")

    for event in agent_engine.stream_query(
        user_id=args.user_id,
        session_id=session_id,
        message=brief,
    ):
        if "content" in event and "parts" in event["content"]:
            for part in event["content"]["parts"]:
                if "text" in part:
                    print(part["text"], end="", flush=True)


if __name__ == "__main__":
    main()
