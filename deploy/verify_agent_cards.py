"""
Agent Card Verification Utility

Validates that all 5 specialist agents expose valid A2A agent cards at /.well-known/agent.json
and that the advertised URLs match the expected execution environment.

Usage:
    # Verify local agents running on ports 8082-8086:
    uv run python deploy/verify_agent_cards.py --local

    # Verify deployed Cloud Run agents from .env:
    uv run python deploy/verify_agent_cards.py [--deployed]
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Ensure the emoji/status markers below print correctly regardless of the
# platform's default console encoding (e.g. Windows terminals defaulting to
# cp1252, which would otherwise crash with UnicodeEncodeError).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Specialist definitions and default local port assignments (matching codelab)
SPECIALISTS = [
    {
        "id": "brand_strategist",
        "name": "Brand Strategist",
        "env_var": "STRATEGIST_AGENT_URL",
        "local_port": 8082,
    },
    {
        "id": "copywriter",
        "name": "Copywriter",
        "env_var": "COPYWRITER_AGENT_URL",
        "local_port": 8083,
    },
    {
        "id": "designer",
        "name": "Designer",
        "env_var": "DESIGNER_AGENT_URL",
        "local_port": 8084,
    },
    {
        "id": "critic",
        "name": "Critic",
        "env_var": "CRITIC_AGENT_URL",
        "local_port": 8085,
    },
    {
        "id": "project_manager",
        "name": "Project Manager",
        "env_var": "PM_AGENT_URL",
        "local_port": 8086,
    },
]


def load_env():
    """Load .env file if available."""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.is_file():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v


def fetch_card(base_url: str, timeout: int = 10) -> tuple[dict | None, str | None]:
    """Fetch /.well-known/agent.json from a base URL."""
    clean_base = base_url.rstrip("/")
    card_url = f"{clean_base}/.well-known/agent.json"
    try:
        req = urllib.request.Request(
            card_url,
            headers={"User-Agent": "A2A-Card-Validator/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None, f"HTTP {response.status}"
            data = json.loads(response.read().decode("utf-8"))
            return data, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return None, f"Connection error: {e.reason}"
    except Exception as e:
        return None, f"Error: {e}"


# Cloud Run services deployed with --min-instances=0 (the default used by
# deploy_all_specialists.py) scale to zero when idle. The Designer in
# particular now pulls in google-cloud-tasks/google-cloud-firestore on top
# of google-adk[a2a], so a cold start can comfortably exceed a single 10s
# request timeout. Retry with a longer timeout to ride out the cold start
# instead of failing the whole check on the first slow request.
COLD_START_RETRY_TIMEOUTS = (10, 30, 30)


def fetch_card_with_retry(base_url: str) -> tuple[dict | None, str | None]:
    """Fetch a card, retrying with longer timeouts to tolerate Cloud Run
    cold starts (scale-to-zero services can take well over 10s to spin up).
    """
    err = None
    for attempt, timeout in enumerate(COLD_START_RETRY_TIMEOUTS, start=1):
        card, err = fetch_card(base_url, timeout=timeout)
        if card is not None:
            return card, None
        if attempt < len(COLD_START_RETRY_TIMEOUTS):
            print(f"   ⏳ Attempt {attempt} failed ({err}); retrying (possible Cloud Run cold start)...")
    return None, err


def verify_local() -> bool:
    """Verify local standalone agent cards on ports 8082-8086."""
    print("\n" + "=" * 70)
    print("Verifying Local A2A Agent Cards (http://localhost:<port>)")
    print("=" * 70)
    all_ok = True

    for spec in SPECIALISTS:
        port = spec["local_port"]
        expected_base = f"http://localhost:{port}"
        print(f"\n🔍 Probing {spec['name']} at {expected_base}...")

        card, err = fetch_card(expected_base)
        if err or not card:
            print(f"   ❌ FAILED to fetch card: {err}")
            print(f"      Ensure the agent is running: PORT={port} uv run agents/{spec['id']}/agent.py")
            all_ok = False
            continue

        # Validate card contents
        card_name = card.get("name", "Unknown")
        card_desc = card.get("description", "No description")
        card_url = card.get("url", "")
        skills = card.get("skills", [])

        print(f"   ✓ Card fetched successfully")
        print(f"     Name:        {card_name}")
        print(f"     Description: {card_desc[:70]}..." if len(card_desc) > 70 else f"     Description: {card_desc}")
        print(f"     Advertised:  {card_url}")
        print(f"     Skills:      {[s.get('id', s.get('name', '')) for s in skills]}")

        # Assert URL matches localhost and port
        parsed = urllib.parse.urlparse(card_url)
        if parsed.hostname not in ("localhost", "127.0.0.1"):
            print(f"   ❌ Advertised host is '{parsed.hostname}', expected 'localhost'")
            all_ok = False
        elif parsed.port != port:
            print(f"   ❌ Advertised port is '{parsed.port}', expected '{port}'")
            all_ok = False
        else:
            print(f"   ✓ Advertised URL is correctly configured for local execution")

    print("\n" + "=" * 70)
    if all_ok:
        print("✅ ALL LOCAL AGENT CARDS VALIDATED SUCCESSFULLY!")
    else:
        print("❌ ONE OR MORE AGENT CARDS FAILED VALIDATION")
    print("=" * 70 + "\n")
    return all_ok


def verify_deployed() -> bool:
    """Verify deployed Cloud Run agent cards from .env."""
    load_env()
    print("\n" + "=" * 70)
    print("Verifying Deployed A2A Agent Cards (Cloud Run HTTPS URLs)")
    print("=" * 70)
    all_ok = True

    for spec in SPECIALISTS:
        env_var = spec["env_var"]
        service_url = os.getenv(env_var)
        print(f"\n🔍 Checking {spec['name']} (${env_var})...")

        if not service_url:
            print(f"   ❌ {env_var} is not set in .env")
            print("      Run `uv run python deploy/deploy_all_specialists.py` first.")
            all_ok = False
            continue

        print(f"   Target URL: {service_url}")

        if "localhost" in service_url or "127.0.0.1" in service_url:
            print(f"   ❌ {env_var} points to localhost ({service_url}) instead of a Cloud Run HTTPS URL.")
            all_ok = False
            continue

        card, err = fetch_card_with_retry(service_url)
        if err or not card:
            print(f"   ❌ FAILED to fetch card from {service_url}: {err}")
            print("      If the service scaled to zero, this may just be a cold start; re-run to confirm.")
            all_ok = False
            continue

        card_name = card.get("name", "Unknown")
        card_desc = card.get("description", "No description")
        card_url = card.get("url", "")
        skills = card.get("skills", [])

        print(f"   ✓ Card fetched successfully")
        print(f"     Name:        {card_name}")
        print(f"     Description: {card_desc[:70]}..." if len(card_desc) > 70 else f"     Description: {card_desc}")
        print(f"     Advertised:  {card_url}")
        print(f"     Skills:      {[s.get('id', s.get('name', '')) for s in skills]}")

        # Assert card_url is HTTPS and matches Cloud Run host
        if not card_url.startswith("https://"):
            print(f"   ❌ Advertised URL '{card_url}' does not use HTTPS protocol.")
            all_ok = False
        elif "localhost" in card_url:
            print(f"   ❌ CRITICAL: Deployed card still advertises 'localhost'!")
            print(f"      The Cloud Run service needs A2A config update: PUBLIC_HOST/PUBLIC_PORT/PROTOCOL.")
            all_ok = False
        else:
            expected_host = urllib.parse.urlparse(service_url).netloc
            actual_host = urllib.parse.urlparse(card_url).netloc
            if expected_host != actual_host and expected_host + ":443" != actual_host:
                print(f"   ⚠️  Warning: Host mismatch: expected '{expected_host}', got '{actual_host}'")
            else:
                print(f"   ✓ Advertised URL correctly matches Cloud Run deployed endpoint")

    print("\n" + "=" * 70)
    if all_ok:
        print("✅ ALL DEPLOYED AGENT CARDS VALIDATED SUCCESSFULLY!")
    else:
        print("❌ ONE OR MORE DEPLOYED AGENT CARDS FAILED VALIDATION")
    print("=" * 70 + "\n")
    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="Validate A2A agent cards for local or deployed specialists."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--local",
        action="store_true",
        help="Validate local agents running on ports 8082-8086.",
    )
    group.add_argument(
        "--deployed",
        action="store_true",
        default=True,
        help="Validate deployed Cloud Run services using URLs in .env (default).",
    )
    args = parser.parse_args()

    if args.local:
        success = verify_local()
    else:
        success = verify_deployed()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
