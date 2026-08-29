#!/usr/bin/env python3
"""
Deploy campaign-driver to its own Cloud Run service, and provision the
`campaigns` Cloud Tasks queue that dispatches to it.

Mirrors the provisioning pattern in deploy_all_specialists.py's
configure_image_generation_infra/provision_cloud_tasks_and_firestore, scoped
to campaign-driver: its own dedicated Cloud Tasks invoker service account,
its own queue (max-attempts=1 per the plan -- a timed-out or 5xx drive must
never be silently re-dispatched as a duplicate campaign), --no-allow-unauthenticated
so only OIDC-authenticated Cloud Tasks pushes reach it, and a service account
scoped to aiplatform.user + Firestore access only.

Usage:
    uv run deploy/deploy_campaign_driver.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Ensure the checkmark/warning markers below print correctly regardless of
# the platform's default console encoding (e.g. Windows terminals defaulting
# to cp1252, which would otherwise crash with UnicodeEncodeError) -- see
# deploy/verify_agent_cards.py for the same guard.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import env_utils

GCLOUD_CMD = "gcloud.cmd" if os.name == "nt" else "gcloud"

SERVICE_NAME = "campaign-driver"
INVOKER_SA_NAME = "campaign-tasks-invoker"
DRIVER_SA_NAME = "campaign-driver-sa"
DEFAULT_QUEUE_NAME = "campaigns"


async def run_command_async(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()


def _write_env_vars_file(env_vars: dict[str, str]) -> str:
    """See deploy_all_specialists.py's _write_env_vars_file for why this
    goes through a file rather than --set-env-vars: env values here
    (AGENT_ENGINE_ID, URLs) don't contain commas today, but this keeps the
    same safe pattern rather than assuming that stays true.
    """
    def _yaml_quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    lines = [f"{_yaml_quote(key)}: {_yaml_quote(value)}" for key, value in env_vars.items()]
    content = "\n".join(lines) + "\n"

    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="campaign-driver-env-")
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


async def provision_queue(project_id: str, tasks_location: str, queue_name: str) -> None:
    """Idempotently create the campaigns Cloud Tasks queue.

    --max-attempts=1: a timed-out or 5xx /drive response must never be
    silently re-dispatched as a duplicate campaign (plan Risk table). The
    driver's own retry logic (main.py's _drain) already handles transient
    mid-stream errors internally; a queue-level retry would race a second
    /drive invocation against the first's still-running drain.
    --max-concurrent-dispatches: the one global admission-control knob the
    plan calls out (Key Decision #2a) -- per-user limits are enforced in
    Firestore by the broker before enqueue, this is the ceiling above that.
    """
    rc, _, err = await run_command_async([
        GCLOUD_CMD, "tasks", "queues", "create", queue_name,
        f"--location={tasks_location}",
        f"--project={project_id}",
        "--max-attempts=1",
        "--max-concurrent-dispatches=5",
        "--max-dispatches-per-second=5",
        "--quiet",
    ])
    if rc == 0:
        print(f"   ✓ Cloud Tasks queue '{queue_name}' ready in {tasks_location}")
    elif "ALREADY_EXISTS" in err:
        print(f"   ✓ Cloud Tasks queue '{queue_name}' already exists")
    else:
        print(f"   ⚠️  Could not create Cloud Tasks queue: {err.strip()}")


async def grant_iam(project_id: str, region: str, driver_sa: str, invoker_sa: str) -> None:
    print("   Granting IAM permissions...")

    rc1, _, err1 = await run_command_async([
        GCLOUD_CMD, "projects", "add-iam-policy-binding", project_id,
        f"--member=serviceAccount:{driver_sa}",
        "--role=roles/aiplatform.user",
        "--quiet",
    ])
    print(f"   {'✓' if rc1 == 0 else '⚠️ '} roles/aiplatform.user -> {driver_sa}" + ("" if rc1 == 0 else f": {err1.strip()}"))

    rc2, _, err2 = await run_command_async([
        GCLOUD_CMD, "projects", "add-iam-policy-binding", project_id,
        f"--member=serviceAccount:{driver_sa}",
        "--role=roles/datastore.user",
        "--quiet",
    ])
    print(f"   {'✓' if rc2 == 0 else '⚠️ '} roles/datastore.user -> {driver_sa}" + ("" if rc2 == 0 else f": {err2.strip()}"))

    rc3, _, err3 = await run_command_async([
        GCLOUD_CMD, "run", "services", "add-iam-policy-binding", SERVICE_NAME,
        f"--member=serviceAccount:{invoker_sa}",
        "--role=roles/run.invoker",
        f"--region={region}",
        f"--project={project_id}",
        "--quiet",
    ])
    print(f"   {'✓' if rc3 == 0 else '⚠️ '} roles/run.invoker on {SERVICE_NAME} -> {invoker_sa}" + ("" if rc3 == 0 else f": {err3.strip()}"))


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
    tasks_location = os.getenv("CAMPAIGN_TASKS_LOCATION", region)
    queue_name = os.getenv("CAMPAIGN_TASKS_QUEUE", DEFAULT_QUEUE_NAME)

    if not agent_engine_id:
        print("Error: AGENT_ENGINE_ID not set. Deploy the orchestrator first "
              "(uv run deploy/deploy_orchestrator.py --action deploy).")
        sys.exit(1)

    driver_dir = Path(__file__).parent.parent / "campaign-driver"

    print(f"Deploying {SERVICE_NAME} to Cloud Run in {region}...")
    print(f"   Project: {project_id}")
    print(f"   Agent Engine: {agent_engine_id}")

    driver_sa = await ensure_service_account(DRIVER_SA_NAME, "Campaign Driver", project_id)
    invoker_sa = await ensure_service_account(INVOKER_SA_NAME, "Campaign Tasks Invoker", project_id)

    # First deploy pass: no CAMPAIGN_TASK_HANDLER_URL yet (unknown until the
    # service exists) -- the handler rejects all requests without it anyway,
    # since _verify_cloud_tasks_oidc_token checks audience == that URL.
    env_vars = {
        "GOOGLE_CLOUD_PROJECT": project_id,
        "CLOUD_RUN_REGION": region,
        "AGENT_ENGINE_ID": agent_engine_id,
        "CAMPAIGN_TASKS_INVOKER_SA": invoker_sa,
    }
    env_vars_file = _write_env_vars_file(env_vars)

    cmd = [
        GCLOUD_CMD, "run", "deploy", SERVICE_NAME,
        "--source=.",
        "--port=8080",
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        f"--service-account={driver_sa}",
        "--no-allow-unauthenticated",
        f"--env-vars-file={env_vars_file}",
        "--memory=512Mi",
        "--cpu=1",
        "--timeout=1800",
        "--no-cpu-throttling",
        "--max-instances=10",
        "--min-instances=0",
        "--quiet",
    ]
    try:
        rc, _, stderr = await run_command_async(cmd, cwd=driver_dir)
    finally:
        os.unlink(env_vars_file)

    if rc != 0:
        print(f"❌ Failed to deploy {SERVICE_NAME}\n   {stderr}")
        sys.exit(1)
    print(f"✓ {SERVICE_NAME} deployed")

    url = await get_service_url(project_id, region)
    if not url:
        print(f"❌ Could not resolve URL for {SERVICE_NAME}")
        sys.exit(1)

    handler_url = url.rstrip("/") + "/drive"
    print(f"   URL: {url}")

    # Second pass: now that the URL is known, set CAMPAIGN_TASK_HANDLER_URL
    # so OIDC audience verification in main.py matches what Cloud Tasks will
    # actually send.
    rc_update, _, err_update = await run_command_async([
        GCLOUD_CMD, "run", "services", "update", SERVICE_NAME,
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        f"--update-env-vars=CAMPAIGN_TASK_HANDLER_URL={handler_url}",
        "--quiet",
    ])
    if rc_update == 0:
        print(f"   ✓ CAMPAIGN_TASK_HANDLER_URL wired: {handler_url}")
    else:
        print(f"   ⚠️  Could not set CAMPAIGN_TASK_HANDLER_URL: {err_update.strip()}")

    await provision_queue(project_id, tasks_location, queue_name)
    await grant_iam(project_id, region, driver_sa, invoker_sa)

    print("\n" + "=" * 70)
    print(f"✓ {SERVICE_NAME} ready at {url}")
    print(f"  Cloud Tasks queue: {queue_name} ({tasks_location})")
    print(f"  Invoker SA: {invoker_sa}")
    print("=" * 70)
    print("\nAdd/update these in .env for the broker to use:")
    print(f"  CAMPAIGN_TASKS_QUEUE={queue_name}")
    print(f"  CAMPAIGN_TASKS_LOCATION={tasks_location}")
    print(f"  CAMPAIGN_TASKS_INVOKER_SA={invoker_sa}")
    print(f"  CAMPAIGN_TASK_HANDLER_URL={handler_url}")


def main():
    asyncio.run(deploy())


if __name__ == "__main__":
    main()
