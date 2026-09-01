#!/usr/bin/env python3
"""
Deploy broker to its own Cloud Run service.

Public (--allow-unauthenticated) since it verifies Firebase ID tokens
itself per-route rather than relying on Cloud Run IAM (unlike
campaign-driver, which is Cloud-Tasks-only). Its service account is scoped
to exactly what the plan's Non-Functional Requirements call for:
cloudtasks.tasks.create on the campaign queue, actAs on the campaign
invoker SA, session-read, Firestore, and URL-signing rights -- no
aiplatform.user beyond what reading sessions requires.

Usage:
    uv run deploy/deploy_broker.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import env_utils

GCLOUD_CMD = "gcloud.cmd" if os.name == "nt" else "gcloud"

SERVICE_NAME = "broker"
BROKER_SA_NAME = "broker-sa"


async def run_command_async(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()


def _write_env_vars_file(env_vars: dict[str, str]) -> str:
    def _yaml_quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    lines = [f"{_yaml_quote(key)}: {_yaml_quote(value)}" for key, value in env_vars.items()]
    content = "\n".join(lines) + "\n"

    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="broker-env-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


async def ensure_service_account(sa_name: str, display_name: str, project_id: str) -> str:
    sa_email = f"{sa_name}@{project_id}.iam.gserviceaccount.com"
    rc, _, err = await run_command_async([
        GCLOUD_CMD, "iam", "service-accounts", "create", sa_name,
        f"--display-name={display_name}",
        f"--project={project_id}",
        "--quiet",
    ])
    if rc == 0:
        print(f"   ✓ Created service account {sa_email}")
    elif "ALREADY_EXISTS" in err or "subject of a conflict" in err:
        print(f"   ✓ Service account {sa_email} already exists")
    else:
        print(f"   ⚠️  Could not create service account {sa_name}: {err.strip()}")
    return sa_email


async def grant_iam(project_id: str, broker_sa: str, invoker_sa: str) -> None:
    print("   Granting IAM permissions...")

    grants = [
        ("roles/cloudtasks.enqueuer", broker_sa),
        ("roles/datastore.user", broker_sa),
        ("roles/aiplatform.user", broker_sa),  # needed to read sessions.events.list
    ]
    for role, member in grants:
        rc, _, err = await run_command_async([
            GCLOUD_CMD, "projects", "add-iam-policy-binding", project_id,
            f"--member=serviceAccount:{member}",
            f"--role={role}",
            "--quiet",
        ])
        print(f"   {'✓' if rc == 0 else '⚠️ '} {role} -> {member}" + ("" if rc == 0 else f": {err.strip()}"))

    # actAs on the campaign invoker SA -- required to mint OIDC tokens for
    # Cloud Tasks tasks targeting campaign-driver (plan Non-Functional
    # Requirements).
    rc_act, _, err_act = await run_command_async([
        GCLOUD_CMD, "iam", "service-accounts", "add-iam-policy-binding", invoker_sa,
        f"--member=serviceAccount:{broker_sa}",
        "--role=roles/iam.serviceAccountUser",
        f"--project={project_id}",
        "--quiet",
    ])
    print(f"   {'✓' if rc_act == 0 else '⚠️ '} roles/iam.serviceAccountUser on {invoker_sa} -> {broker_sa}" + ("" if rc_act == 0 else f": {err_act.strip()}"))

    # Bucket-level URL-signing: iam.serviceAccountTokenCreator on itself,
    # mirroring the SIGNING_SERVICE_ACCOUNT pattern from
    # deploy_all_specialists.py -- not currently exercised by any broker
    # route (image URLs come pre-signed via get_image_links, per Step 3's
    # decision), granted defensively since Functional Requirement 6 names
    # URL-signing as a broker responsibility.
    rc_tok, _, err_tok = await run_command_async([
        GCLOUD_CMD, "iam", "service-accounts", "add-iam-policy-binding", broker_sa,
        f"--member=serviceAccount:{broker_sa}",
        "--role=roles/iam.serviceAccountTokenCreator",
        f"--project={project_id}",
        "--quiet",
    ])
    print(f"   {'✓' if rc_tok == 0 else 'ℹ️ '} roles/iam.serviceAccountTokenCreator on {broker_sa}" + ("" if rc_tok == 0 else f": {err_tok.strip()}"))


async def ensure_firestore_index(project_id: str) -> None:
    """Create the composite index `campaigns` needs for
    campaign_store.list_campaigns_for_user's (user_id ==, created_at
    order_by) query -- GET /campaigns 404s with FAILED_PRECONDITION without
    it. Discovered by running the broker's Firestore calls for real against
    a fresh collection during Step 3 validation; count_active_campaigns'
    (user_id ==, status in [...]) query needs no index since it has no
    order_by.
    """
    rc, _, err = await run_command_async([
        GCLOUD_CMD, "firestore", "indexes", "composite", "create",
        "--collection-group=campaigns",
        "--field-config=field-path=user_id,order=ascending",
        "--field-config=field-path=created_at,order=descending",
        f"--project={project_id}",
        "--quiet",
    ])
    if rc == 0:
        print("   ✓ Firestore composite index for 'campaigns' created (may take a few minutes to build)")
    elif "already exists" in err.lower() or "ALREADY_EXISTS" in err:
        print("   ✓ Firestore composite index for 'campaigns' already exists")
    else:
        print(f"   ⚠️  Could not create Firestore composite index: {err.strip()}")


async def get_service_url(project_id: str, region: str) -> str | None:
    rc, stdout, _ = await run_command_async([
        GCLOUD_CMD, "run", "services", "describe", SERVICE_NAME,
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        "--format=value(status.url)",
    ])
    return stdout.strip() if rc == 0 and stdout.strip() else None


async def deploy() -> None:
    config = env_utils.load_env_file()
    try:
        env_utils.validate_required_vars(config)
    except ValueError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    project_id = config["PROJECT_ID"]
    region = config["REGION"]
    agent_engine_id = os.getenv("AGENT_ENGINE_ID")
    invoker_sa = os.getenv("CAMPAIGN_TASKS_INVOKER_SA")
    task_handler_url = os.getenv("CAMPAIGN_TASK_HANDLER_URL")
    tasks_location = os.getenv("CAMPAIGN_TASKS_LOCATION", region)
    tasks_queue = os.getenv("CAMPAIGN_TASKS_QUEUE", "campaigns")

    if not agent_engine_id:
        print("Error: AGENT_ENGINE_ID not set. Deploy the orchestrator first.")
        sys.exit(1)
    if not invoker_sa or not task_handler_url:
        print("Error: CAMPAIGN_TASKS_INVOKER_SA / CAMPAIGN_TASK_HANDLER_URL not set. "
              "Deploy campaign-driver first (uv run deploy/deploy_campaign_driver.py).")
        sys.exit(1)

    broker_dir = Path(__file__).parent.parent / "broker"

    print(f"Deploying {SERVICE_NAME} to Cloud Run in {region}...")
    broker_sa = await ensure_service_account(BROKER_SA_NAME, "Broker", project_id)

    allowed_origins = os.getenv("BROKER_ALLOWED_ORIGINS", "")
    env_vars = {
        "GOOGLE_CLOUD_PROJECT": project_id,
        "CLOUD_RUN_REGION": region,
        "AGENT_ENGINE_ID": agent_engine_id,
        "CAMPAIGN_TASKS_INVOKER_SA": invoker_sa,
        "CAMPAIGN_TASK_HANDLER_URL": task_handler_url,
        "CAMPAIGN_TASKS_LOCATION": tasks_location,
        "CAMPAIGN_TASKS_QUEUE": tasks_queue,
        "BROKER_ALLOWED_ORIGINS": allowed_origins,
        "STRATEGIST_AGENT_URL": os.getenv("STRATEGIST_AGENT_URL", ""),
        "COPYWRITER_AGENT_URL": os.getenv("COPYWRITER_AGENT_URL", ""),
        "DESIGNER_AGENT_URL": os.getenv("DESIGNER_AGENT_URL", ""),
        "CRITIC_AGENT_URL": os.getenv("CRITIC_AGENT_URL", ""),
        "PM_AGENT_URL": os.getenv("PM_AGENT_URL", ""),
    }
    env_vars_file = _write_env_vars_file(env_vars)

    cmd = [
        GCLOUD_CMD, "run", "deploy", SERVICE_NAME,
        "--source=.",
        "--port=8080",
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        f"--service-account={broker_sa}",
        "--allow-unauthenticated",  # public entry point; auth.py verifies Firebase tokens per-route
        f"--env-vars-file={env_vars_file}",
        "--memory=512Mi",
        "--cpu=1",
        "--timeout=60",
        "--max-instances=10",
        "--min-instances=0",
        "--quiet",
    ]
    try:
        rc, _, stderr = await run_command_async(cmd, cwd=broker_dir)
    finally:
        os.unlink(env_vars_file)

    if rc != 0:
        print(f"❌ Failed to deploy {SERVICE_NAME}\n   {stderr}")
        sys.exit(1)
    print(f"✓ {SERVICE_NAME} deployed")

    url = await get_service_url(project_id, region)
    if url:
        print(f"   URL: {url}")

    await grant_iam(project_id, broker_sa, invoker_sa)
    await ensure_firestore_index(project_id)

    print("\n" + "=" * 70)
    print(f"✓ {SERVICE_NAME} ready at {url}")
    print("=" * 70)


def main():
    asyncio.run(deploy())


if __name__ == "__main__":
    main()
