# Copyright 2026 Saoussen Chaabnia
# Modifications Copyright 2026 Animesh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#!/usr/bin/env python3
"""
Deploy all 5 specialist agents to Cloud Run and collect their URLs
Supports sequential deployment and automatic GCS / IAM permission configuration.

Usage:
    uv run python deploy/deploy_all_specialists.py
    uv run python deploy/deploy_all_specialists.py --agent designer
    uv run python deploy/deploy_all_specialists.py -a designer -a critic
"""

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Import env_utils from same directory
sys.path.insert(0, str(Path(__file__).parent))
import env_utils

GCLOUD_CMD = "gcloud.cmd" if os.name == "nt" else "gcloud"

# Agent configuration for deployment
AGENTS = [
    {
        "name": "brand-strategist",
        "dir": "brand_strategist",
        "port": 8080,
    },
    {
        "name": "copywriter",
        "dir": "copywriter",
        "port": 8080,
    },
    {
        "name": "designer",
        "dir": "designer",
        "port": 8080,
    },
    {
        "name": "critic",
        "dir": "critic",
        "port": 8080,
    },
    {
        "name": "project-manager",
        "dir": "project_manager",
        "port": 8080,
    },
]


async def run_command_async(
    cmd: list[str], cwd: Path | None = None
) -> tuple[int, str, str]:
    """
    Run a command asynchronously

    Args:
        cmd: Command as list of strings
        cwd: Working directory for command

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd
    )

    try:
        stdout, stderr = await process.communicate()
        return process.returncode, stdout.decode(), stderr.decode()
    except asyncio.CancelledError:
        process.terminate()
        await process.wait()
        raise


async def _add_secret_version(
    secret_id: str, value: str, project_id: str
) -> tuple[int, str, str]:
    """Add a version to an existing Secret Manager secret, passing the value via stdin."""
    process = await asyncio.create_subprocess_exec(
        GCLOUD_CMD, "secrets", "versions", "add", secret_id,
        "--data-file=-",
        f"--project={project_id}",
        "--quiet",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate(input=value.encode())
        return process.returncode, stdout.decode(), stderr.decode()
    except asyncio.CancelledError:
        process.terminate()
        await process.wait()
        raise


async def setup_notion_secrets(project_id: str) -> dict[str, str]:
    """
    Store Notion credentials in Secret Manager.
    Creates each secret if it doesn't exist, then adds a new version.

    Returns:
        {ENV_VAR_NAME: "secret-id:latest"} for --set-secrets,
        or empty dict if Notion credentials are not configured.
    """
    notion_token = os.getenv("NOTION_TOKEN")
    notion_db_id = os.getenv("NOTION_PROJECT_DATABASE_ID")
    notion_tasks_db_id = os.getenv("NOTION_TASKS_DATABASE_ID")

    if not notion_token or not notion_db_id:
        return {}

    credentials = {
        "NOTION_TOKEN": ("notion-token", notion_token),
        "NOTION_PROJECT_DATABASE_ID": ("notion-project-db-id", notion_db_id),
    }
    if notion_tasks_db_id:
        credentials["NOTION_TASKS_DATABASE_ID"] = ("notion-tasks-db-id", notion_tasks_db_id)

    secret_refs = {}
    for env_var, (secret_id, value) in credentials.items():
        # Create secret (idempotent - ALREADY_EXISTS is not an error)
        await run_command_async([
            GCLOUD_CMD, "secrets", "create", secret_id,
            f"--project={project_id}",
            "--replication-policy=automatic",
            "--quiet",
        ])
        # Add new version with the credential value
        returncode, _, stderr = await _add_secret_version(secret_id, value, project_id)
        if returncode == 0:
            secret_refs[env_var] = f"{secret_id}:latest"
            print(f"   ✓ {secret_id} stored in Secret Manager")
        else:
            print(f"   Warning: Could not store {secret_id}: {stderr.strip()}")

    return secret_refs


async def grant_pm_secret_access(project_id: str, secret_refs: dict[str, str]) -> None:
    """
    Grant the Project Manager Cloud Run service account
    roles/secretmanager.secretAccessor on each Notion secret.
    Uses the default Compute Engine SA (Cloud Run default).
    """
    if not secret_refs:
        return

    _, project_number, _ = await run_command_async([
        GCLOUD_CMD, "projects", "describe", project_id,
        "--format=value(projectNumber)",
    ])
    sa_email = f"{project_number.strip()}-compute@developer.gserviceaccount.com"
    print(f"   Granting Secret Manager access to {sa_email}...")

    for _, secret_path in secret_refs.items():
        secret_id = secret_path.split(":")[0]
        returncode, _, stderr = await run_command_async([
            GCLOUD_CMD, "secrets", "add-iam-policy-binding", secret_id,
            f"--member=serviceAccount:{sa_email}",
            "--role=roles/secretmanager.secretAccessor",
            f"--project={project_id}",
            "--quiet",
        ])
        if returncode == 0:
            print(f"   ✓ Access granted to {secret_id}")
        else:
            print(f"   Warning: Could not grant access to {secret_id}: {stderr.strip()}")


def _is_quota_exhausted_error(e: Exception) -> bool:
    """True if `e` represents a 429 / RESOURCE_EXHAUSTED response."""
    code = getattr(e, "code", None)
    if code == 429:
        return True
    return "RESOURCE_EXHAUSTED" in str(e).upper()


async def _verify_image_gen_regions(
    regions: list[str], project_id: str, image_model: str
) -> list[str]:
    """
    Confirm the configured image-generation model is actually published in
    each candidate Vertex AI region before wiring it into IMAGE_GEN_REGIONS.

    Some Gemini image-generation models (e.g. preview/limited-availability
    ones) are only published on a subset of regional endpoints, or only on
    the "global" endpoint. Blindly forwarding every configured region into
    the designer's failover list causes a runtime
    "Publisher model ... was not found" error the first time that region is
    tried. This check runs once at deploy time so IMAGE_GEN_REGIONS only
    ever contains regions Vertex AI actually serves this model from. This
    re-runs on every deploy, so changing GEMINI_IMAGE_MODEL in .env is
    automatically re-validated.

    IMPORTANT: this deliberately does NOT use the cheaper `models.get`
    metadata call. Vertex AI's publisher-model catalog (what `models.get`
    reads) is mirrored to every region for browsing purposes, so `get`
    happily returns metadata for a model even in regions where it can't
    actually be invoked -- it does not reflect real per-region serving
    availability. Only an actual `generate_content` call exercises the
    same regional serving path the Designer uses at runtime, so that's
    what we probe here (with a trivial prompt to keep cost minimal).
    """
    from google import genai
    from google.genai import types as genai_types

    def _check(region: str) -> bool:
        try:
            client = genai.Client(vertexai=True, project=project_id, location=region)
            client.models.generate_content(
                model=image_model,
                contents="test",
                config=genai_types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    http_options=genai_types.HttpOptions(timeout=30_000),
                ),
            )
            return True
        except Exception as e:
            # A quota/rate-limit error still means the model IS servable in
            # this region -- only treat "not found"/unpublished as
            # unavailable, so a transient 429 during deploy doesn't
            # wrongly drop an otherwise-valid region.
            if _is_quota_exhausted_error(e):
                return True
            return False

    print(f"   Verifying '{image_model}' availability across regions: {', '.join(regions)}...")
    available: list[str] = []
    for region in regions:
        region = region.strip()
        if not region:
            continue
        ok = await asyncio.to_thread(_check, region)
        if ok:
            print(f"   ✓ {region}: model available")
            available.append(region)
        else:
            print(f"   ⚠️  {region}: '{image_model}' not published here, excluding from failover list")

    if not available:
        print(
            f"   Warning: '{image_model}' wasn't confirmed available in any of "
            f"{regions}; falling back to the 'global' endpoint."
        )
        return ["global"]

    return available


def _write_env_vars_file(env_vars: dict[str, str]) -> str:
    """
    Write `env_vars` to a temporary YAML file suitable for `gcloud run
    deploy --env-vars-file=...`.

    Using a file (instead of a `--set-env-vars=...` string) sidesteps shell
    and batch-file argument re-parsing altogether -- only a file path is
    passed on the command line, so values are free to contain commas,
    pipes, or any other characters without needing gcloud's delimiter
    escaping tricks (which break when `gcloud.cmd` is spawned on Windows).
    """
    def _yaml_quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    lines = [f"{_yaml_quote(key)}: {_yaml_quote(value)}" for key, value in env_vars.items()]
    content = "\n".join(lines) + "\n"

    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="cloud-run-env-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


async def deploy_single_agent(
    agent_config: dict, project_id: str, region: str
) -> str | None:
    """
    Deploy a single agent to Cloud Run

    Args:
        agent_config: Agent configuration dict
        project_id: GCP project ID
        region: GCP region

    Returns:
        Agent URL or None if deployment failed
    """
    name = agent_config["name"]
    agent_dir = agent_config["dir"]

    print(f"🚀 Deploying {name}...")

    # Build Cloud Run deployment command
    agent_path = Path(__file__).parent.parent / "agents" / agent_dir

    # Build environment variables
    # GOOGLE_CLOUD_LOCATION controls model routing - may be "global" for preview
    # models. Read from env rather than using the Cloud Run deployment region.
    # NOTE: env var values (e.g. IMAGE_GEN_REGIONS below) may themselves
    # contain commas, so gcloud's default comma-delimited --set-env-vars
    # syntax (KEY1=VAL1,KEY2=VAL2) can't be used -- a comma inside a value
    # is indistinguishable from the next KEY=VALUE separator. A previous
    # version worked around this with gcloud's alternate-delimiter escaping
    # (`^|^` prefix), but on Windows `gcloud` is a `.cmd` batch file, and
    # spawning it via subprocess routes the whole argument list back through
    # cmd.exe, which re-parses literal "|" characters in our arguments as
    # real pipe operators (splitting our command in two) instead of passing
    # them through as data -- this is what caused
    # "'GOOGLE_CLOUD_PROJECT' is not recognized as an internal or external
    # command" once IMAGE_GEN_REGIONS values started flowing through it.
    # Writing the env vars to a YAML file and using `--env-vars-file` avoids
    # shell/batch re-parsing entirely, since only a file path is passed on
    # the command line. See `gcloud topic escaping` / `gcloud run deploy --help`.
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    model_location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    env_vars_dict = {
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "GOOGLE_CLOUD_PROJECT": project_id,
        "GOOGLE_CLOUD_LOCATION": model_location,
        "GEMINI_MODEL": gemini_model,
    }

    # Add GCS bucket for image generation/review agents
    gcs_bucket = os.getenv("GCS_IMAGES_BUCKET", "")
    if gcs_bucket and name in ("designer", "critic"):
        print(f"   Adding GCS_IMAGES_BUCKET to {name}...")
        env_vars_dict["GCS_IMAGES_BUCKET"] = gcs_bucket

    # Pass image model overrides to designer
    gemini_image_model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1")
    gemini_image_backup_model = os.getenv("GEMINI_IMAGE_BACKUP_MODEL", "gemini-3.1-flash-lite-image")
    if name == "designer":
        if gemini_image_model:
            env_vars_dict["GEMINI_IMAGE_MODEL"] = gemini_image_model
        if gemini_image_backup_model:
            env_vars_dict["GEMINI_IMAGE_BACKUP_MODEL"] = gemini_image_backup_model

    # Image-generation queue/rate-limit/failover tunables (designer only)
    if name == "designer":
        configured_regions = os.getenv("IMAGE_GEN_REGIONS", "global")
        image_model_for_check = gemini_image_model or "gemini-nano-banana-2.1"
        verified_regions = await _verify_image_gen_regions(
            [r.strip() for r in configured_regions.split(",") if r.strip()],
            project_id,
            image_model_for_check,
        )
        image_gen_regions = ",".join(verified_regions)
        tasks_location = os.getenv("GCP_TASKS_LOCATION", region)
        tasks_queue = os.getenv("IMAGE_GEN_TASKS_QUEUE", "image-generation")
        rate_limit_capacity = os.getenv("IMAGE_GEN_RATE_LIMIT_CAPACITY", "3")
        rate_limit_window = os.getenv("IMAGE_GEN_RATE_LIMIT_WINDOW_SECONDS", "60")
        job_poll_interval = os.getenv("IMAGE_GEN_JOB_POLL_INTERVAL_SECONDS", "1")
        job_timeout = os.getenv("IMAGE_GEN_JOB_TIMEOUT_SECONDS", "170")
        env_vars_dict.update({
            "IMAGE_GEN_REGIONS": image_gen_regions,
            "GCP_TASKS_LOCATION": tasks_location,
            "IMAGE_GEN_TASKS_QUEUE": tasks_queue,
            "IMAGE_GEN_RATE_LIMIT_CAPACITY": rate_limit_capacity,
            "IMAGE_GEN_RATE_LIMIT_WINDOW_SECONDS": rate_limit_window,
            "IMAGE_GEN_JOB_POLL_INTERVAL_SECONDS": job_poll_interval,
            "IMAGE_GEN_JOB_TIMEOUT_SECONDS": job_timeout,
        })

    # Store Notion credentials in Secret Manager for project-manager
    secret_refs: dict[str, str] = {}
    if name == "project-manager":
        if os.getenv("NOTION_TOKEN") and os.getenv("NOTION_PROJECT_DATABASE_ID"):
            print(f"   Storing Notion credentials in Secret Manager...")
            secret_refs = await setup_notion_secrets(project_id)
            if secret_refs:
                # Grant SA access before deploy so the service starts cleanly
                await grant_pm_secret_access(project_id, secret_refs)
        else:
            print(
                f"   Warning: NOTION_TOKEN or NOTION_PROJECT_DATABASE_ID not set"
                f" - {name} will work without Notion integration"
            )

    env_vars_file = _write_env_vars_file(env_vars_dict)

    cmd = [
        GCLOUD_CMD,
        "run",
        "deploy",
        name,
        "--source=.",
        "--port=8080",
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        "--allow-unauthenticated",  # Allow public access to agent cards
        f"--env-vars-file={env_vars_file}",
        "--memory=1Gi",
        "--cpu=1",
        "--timeout=300",
        "--max-instances=10",
        "--min-instances=0",
        "--quiet",
    ]
    if secret_refs:
        secrets_flag = ",".join(f"{k}={v}" for k, v in secret_refs.items())
        cmd.append(f"--set-secrets={secrets_flag}")

    # Run deployment
    try:
        returncode, stdout, stderr = await run_command_async(cmd, cwd=agent_path)
    except Exception as e:
        print(f"❌ Failed to deploy {name}: {e}")
        return None
    finally:
        os.unlink(env_vars_file)

    if returncode != 0:
        print(f"❌ Failed to deploy {name}")
        print(f"   Error: {stderr}")
        return None

    print(f"✓ {name} deployed successfully")

    # Get service URL
    url = await get_service_url(name, project_id, region)

    if url:
        # Update A2A configuration
        await update_agent_a2a_config(name, url, project_id, region)

    # Grant Designer SA write access to the GCS images bucket
    if name == "designer" and url and os.getenv("GCS_IMAGES_BUCKET"):
        await grant_designer_gcs_access(name, project_id, region)

    # Provision the Cloud Tasks queue / Firestore DB the image-generation
    # job queue and rate limiter depend on, and wire up the invoker SA.
    if name == "designer" and url:
        await configure_image_generation_infra(name, url, project_id, region)

    return url


async def configure_image_generation_infra(
    service_name: str, url: str, project_id: str, region: str
) -> None:
    """
    Provision the Cloud Tasks queue and Firestore database used by the
    Designer's image-generation job queue and rate limiter, ensure the
    dedicated Cloud Tasks invoker service account exists, grant it and the
    Designer's own service account the IAM roles they need, and point the
    Designer at its own internal task handler URL.
    """
    await provision_cloud_tasks_and_firestore(project_id, region)

    invoker_sa = await ensure_image_gen_invoker_service_account(project_id)

    _, designer_sa, _ = await run_command_async([
        GCLOUD_CMD, "run", "services", "describe", service_name,
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        "--format=value(spec.template.spec.serviceAccountName)",
    ])
    designer_sa = designer_sa.strip()
    if not designer_sa:
        _, project_number, _ = await run_command_async([
            GCLOUD_CMD, "projects", "describe", project_id,
            "--format=value(projectNumber)",
        ])
        designer_sa = f"{project_number.strip()}-compute@developer.gserviceaccount.com"

    await grant_image_generation_iam(project_id, region, designer_sa, invoker_sa)

    task_handler_url = url.rstrip("/") + "/internal/tasks/generate-image"
    env_vars_update = f"IMAGE_GEN_TASKS_INVOKER_SA={invoker_sa},IMAGE_GEN_TASK_HANDLER_URL={task_handler_url}"
    returncode, _, stderr = await run_command_async([
        GCLOUD_CMD, "run", "services", "update", service_name,
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        f"--update-env-vars={env_vars_update}",
        "--quiet",
    ])
    if returncode == 0:
        print(f"   ✓ Image generation task handler wired: {task_handler_url}")
    else:
        print(f"   ⚠️  Could not set image-generation task handler env vars: {stderr.strip()}")


async def provision_cloud_tasks_and_firestore(project_id: str, region: str) -> None:
    """
    Idempotently create the Cloud Tasks queue and Firestore database used by
    the Designer's image-generation job queue and rate limiter. Queue
    dispatch rate/concurrency is set here via configuration, matching the
    current Vertex AI RPM limit -- no custom concurrency-limiting code.
    """
    tasks_location = os.getenv("GCP_TASKS_LOCATION", region)
    queue_name = os.getenv("IMAGE_GEN_TASKS_QUEUE", "image-generation")

    print("\n⏳ Provisioning Cloud Tasks queue and Firestore database...")

    rc, _, err = await run_command_async([
        GCLOUD_CMD, "tasks", "queues", "create", queue_name,
        f"--location={tasks_location}",
        f"--project={project_id}",
        "--max-dispatches-per-second=1",
        "--max-concurrent-dispatches=2",
        "--max-attempts=3",
        "--min-backoff=5s",
        "--max-backoff=60s",
        "--quiet",
    ])
    if rc == 0:
        print(f"   ✓ Cloud Tasks queue '{queue_name}' ready in {tasks_location}")
    elif "ALREADY_EXISTS" in err:
        print(f"   ✓ Cloud Tasks queue '{queue_name}' already exists")
    else:
        print(f"   ⚠️  Could not create Cloud Tasks queue: {err.strip()}")

    rc_fs, _, err_fs = await run_command_async([
        GCLOUD_CMD, "firestore", "databases", "create",
        f"--location={region}",
        "--type=firestore-native",
        f"--project={project_id}",
        "--quiet",
    ])
    if rc_fs == 0:
        print(f"   ✓ Firestore database created in {region}")
    elif "ALREADY_EXISTS" in err_fs:
        print(f"   ✓ Firestore database already exists")
    else:
        print(f"   ⚠️  Could not create Firestore database: {err_fs.strip()}")


async def ensure_image_gen_invoker_service_account(project_id: str) -> str:
    """
    Idempotently create the dedicated service account Cloud Tasks uses to
    authenticate its push requests to the Designer's internal task handler.
    """
    sa_name = "image-gen-tasks-invoker"
    sa_email = f"{sa_name}@{project_id}.iam.gserviceaccount.com"

    rc, _, err = await run_command_async([
        GCLOUD_CMD, "iam", "service-accounts", "create", sa_name,
        "--display-name=Image Generation Cloud Tasks Invoker",
        f"--project={project_id}",
        "--quiet",
    ])
    if rc == 0:
        print(f"   ✓ Created Cloud Tasks invoker service account {sa_email}")
    elif "ALREADY_EXISTS" in err:
        print(f"   ✓ Cloud Tasks invoker service account {sa_email} already exists")
    else:
        print(f"   ⚠️  Could not create invoker service account: {err.strip()}")

    return sa_email


async def grant_image_generation_iam(
    project_id: str, region: str, designer_sa: str, invoker_sa: str
) -> None:
    """
    Grant the Designer service account permission to enqueue Cloud Tasks and
    read/write Firestore, and grant the Cloud Tasks invoker service account
    permission to invoke the Designer Cloud Run service.
    """
    print("   Granting Cloud Tasks/Firestore IAM permissions...")

    rc1, _, err1 = await run_command_async([
        GCLOUD_CMD, "projects", "add-iam-policy-binding", project_id,
        f"--member=serviceAccount:{designer_sa}",
        "--role=roles/cloudtasks.enqueuer",
        "--quiet",
    ])
    if rc1 == 0:
        print(f"   ✓ Granted roles/cloudtasks.enqueuer to {designer_sa}")
    else:
        print(f"   ⚠️  Could not grant roles/cloudtasks.enqueuer: {err1.strip()}")

    rc2, _, err2 = await run_command_async([
        GCLOUD_CMD, "projects", "add-iam-policy-binding", project_id,
        f"--member=serviceAccount:{designer_sa}",
        "--role=roles/datastore.user",
        "--quiet",
    ])
    if rc2 == 0:
        print(f"   ✓ Granted roles/datastore.user to {designer_sa}")
    else:
        print(f"   ⚠️  Could not grant roles/datastore.user: {err2.strip()}")

    rc3, _, err3 = await run_command_async([
        GCLOUD_CMD, "run", "services", "add-iam-policy-binding", "designer",
        f"--member=serviceAccount:{invoker_sa}",
        "--role=roles/run.invoker",
        f"--region={region}",
        f"--project={project_id}",
        "--quiet",
    ])
    if rc3 == 0:
        print(f"   ✓ Granted roles/run.invoker on designer to {invoker_sa}")
    else:
        print(f"   ⚠️  Could not grant roles/run.invoker: {err3.strip()}")


async def get_service_url(
    service_name: str, project_id: str, region: str
) -> str | None:
    """
    Get Cloud Run service URL after deployment

    Args:
        service_name: Name of the Cloud Run service
        project_id: GCP project ID
        region: GCP region

    Returns:
        Service URL or None if not found
    """
    cmd = [
        GCLOUD_CMD,
        "run",
        "services",
        "describe",
        service_name,
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        "--format=value(status.url)",
    ]

    returncode, stdout, stderr = await run_command_async(cmd)

    if returncode != 0:
        print(f"   Warning: Could not get URL for {service_name}")
        return None

    url = stdout.strip()
    print(f"   URL: {url}")
    return url


async def update_agent_a2a_config(
    service_name: str, url: str, project_id: str, region: str
) -> None:
    """
    Update deployed agent with A2A configuration (PUBLIC_HOST, PORT, PROTOCOL).
    Notion credentials are handled via Secret Manager at deploy time, not here.

    Args:
        service_name: Name of the Cloud Run service
        url: Service URL
        project_id: GCP project ID
        region: GCP region
    """
    # Extract PUBLIC_HOST from URL (remove https:// and trailing path)
    public_host = url.replace("https://", "").replace("http://", "").split("/")[0]

    print(f"   Updating A2A config for {service_name}...")

    # Build environment variables update
    env_vars_update = f"PUBLIC_HOST={public_host},PUBLIC_PORT=443,PROTOCOL=https"

    cmd = [
        GCLOUD_CMD,
        "run",
        "services",
        "update",
        service_name,
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        f"--update-env-vars={env_vars_update}",
        "--quiet",
    ]

    returncode, stdout, stderr = await run_command_async(cmd)

    if returncode == 0:
        print(f"   ✓ A2A config updated for {service_name}")
    else:
        print(f"   Warning: Could not update A2A config for {service_name}: {stderr}")


async def grant_designer_gcs_access(
    service_name: str, project_id: str, region: str
) -> None:
    """
    Grant the Designer Cloud Run service account storage.objectAdmin / objectCreator on GCS bucket.
    Called automatically after designer deployment when GCS_IMAGES_BUCKET is set.
    """
    bucket = os.getenv("GCS_IMAGES_BUCKET")
    if not bucket:
        return

    print(f"   Granting GCS access to {service_name} service account...")

    # Retrieve the service account email used by the Cloud Run service
    _, sa_email, _ = await run_command_async([
        GCLOUD_CMD, "run", "services", "describe", service_name,
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        "--format=value(spec.template.spec.serviceAccountName)",
    ])
    sa_email = sa_email.strip()

    # Fall back to compute default SA if no custom SA is configured
    if not sa_email:
        _, project_number, _ = await run_command_async([
            GCLOUD_CMD, "projects", "describe", project_id,
            "--format=value(projectNumber)",
        ])
        sa_email = f"{project_number.strip()}-compute@developer.gserviceaccount.com"

    returncode, _, stderr = await run_command_async([
        GCLOUD_CMD, "storage", "buckets", "add-iam-policy-binding",
        f"gs://{bucket}",
        f"--member=serviceAccount:{sa_email}",
        "--role=roles/storage.objectAdmin",
        f"--project={project_id}",
    ])

    if returncode == 0:
        print(f"   ✓ GCS objectAdmin access granted to {sa_email}")
    else:
        print(f"   Warning: Could not grant GCS access: {stderr.strip()}")
        print(f"   Manual fix: gcloud storage buckets add-iam-policy-binding gs://{bucket} --member=serviceAccount:{sa_email} --role=roles/storage.objectAdmin")


async def grant_all_storage_and_iam_permissions(
    project_id: str, region: str, agent_names: list[str]
) -> None:
    """
    Configure GCS bucket and IAM permissions across all specialist services.
    Ensures Designer can write images, Critic/PM/Orchestrator can read them,
    and signing SAs have serviceAccountTokenCreator for signed URLs.
    """
    bucket = os.getenv("GCS_IMAGES_BUCKET")
    if not bucket:
        print("ℹ️  GCS_IMAGES_BUCKET not set in environment, skipping bucket IAM pass.")
        return

    print("\n⏳ Configuring GCS bucket and IAM permissions...")

    # Discover service accounts for deployed services
    sa_emails = set()
    for name in agent_names:
        _, sa_email, _ = await run_command_async([
            GCLOUD_CMD, "run", "services", "describe", name,
            "--platform=managed",
            f"--region={region}",
            f"--project={project_id}",
            "--format=value(spec.template.spec.serviceAccountName)",
        ])
        sa = sa_email.strip()
        if sa:
            sa_emails.add(sa)

    # Fallback to Compute Engine default SA if none discovered
    _, project_number_out, _ = await run_command_async([
        GCLOUD_CMD, "projects", "describe", project_id,
        "--format=value(projectNumber)",
    ])
    project_number = project_number_out.strip()
    default_sa = f"{project_number}-compute@developer.gserviceaccount.com"
    signing_sa = os.getenv("SIGNING_SERVICE_ACCOUNT") or default_sa

    if not sa_emails:
        sa_emails.add(default_sa)

    # Add Reasoning Engine and dedicated component service accounts to the token creator grant list
    token_invokers = set(sa_emails)
    if project_number:
        token_invokers.add(f"service-{project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com")
    token_invokers.add(f"broker-sa@{project_id}.iam.gserviceaccount.com")
    token_invokers.add(f"campaign-driver-sa@{project_id}.iam.gserviceaccount.com")

    # Get active gcloud user account if available
    _, active_account_out, _ = await run_command_async([
        GCLOUD_CMD, "config", "get-value", "account",
    ])
    active_account = active_account_out.strip()

    for sa in sa_emails:
        # Grant Storage Object Admin on the campaign images bucket
        rc, _, err = await run_command_async([
            GCLOUD_CMD, "storage", "buckets", "add-iam-policy-binding",
            f"gs://{bucket}",
            f"--member=serviceAccount:{sa}",
            "--role=roles/storage.objectAdmin",
            f"--project={project_id}",
            "--quiet",
        ])
        if rc == 0:
            print(f"   ✓ Granted roles/storage.objectAdmin on gs://{bucket} to {sa}")
        else:
            print(f"   ⚠️  Could not grant storage.objectAdmin to {sa}: {err.strip()}")
            print(f"      Run manually: gcloud storage buckets add-iam-policy-binding gs://{bucket} --member=serviceAccount:{sa} --role=roles/storage.objectAdmin")

        # Grant serviceAccountTokenCreator on itself for V4 signed URL signing
        rc_tok, _, err_tok = await run_command_async([
            GCLOUD_CMD, "iam", "service-accounts", "add-iam-policy-binding",
            sa,
            f"--member=serviceAccount:{sa}",
            "--role=roles/iam.serviceAccountTokenCreator",
            f"--project={project_id}",
            "--quiet",
        ])
        if rc_tok == 0:
            print(f"   ✓ Granted roles/iam.serviceAccountTokenCreator to {sa}")
        else:
            print(f"   ℹ️  Token creator grant on {sa}: {err_tok.strip() if err_tok else 'Skipped or already present'}")

        # Grant Vertex AI User
        await run_command_async([
            GCLOUD_CMD, "projects", "add-iam-policy-binding",
            project_id,
            f"--member=serviceAccount:{sa}",
            "--role=roles/aiplatform.user",
            "--quiet",
        ])

    # Grant token creator on the signing SA to Reasoning Engine, Driver, Broker, and active user
    for invoker in token_invokers:
        member = f"serviceAccount:{invoker}"
        await run_command_async([
            GCLOUD_CMD, "iam", "service-accounts", "add-iam-policy-binding",
            signing_sa,
            f"--member={member}",
            "--role=roles/iam.serviceAccountTokenCreator",
            f"--project={project_id}",
            "--quiet",
        ])

    if active_account:
        member_user = f"user:{active_account}"
        await run_command_async([
            GCLOUD_CMD, "iam", "service-accounts", "add-iam-policy-binding",
            signing_sa,
            f"--member={member_user}",
            "--role=roles/iam.serviceAccountTokenCreator",
            f"--project={project_id}",
            "--quiet",
        ])


async def deploy_all_agents(
    project_id: str, region: str, agents: list[dict] | None = None
) -> dict[str, str]:
    """
    Deploy the given agents sequentially and collect their URLs.
    Sequential deployment avoids Cloud Build polling quota (60 req/min/user).

    Args:
        project_id: GCP project ID
        region: GCP region
        agents: Subset of AGENTS to deploy. Defaults to all agents.
    """
    agents = agents if agents is not None else AGENTS

    print("\n" + "=" * 70)
    if len(agents) == len(AGENTS):
        print("Deploying all specialist agents to Cloud Run (sequential)")
    else:
        names = ", ".join(a["name"] for a in agents)
        print(f"Deploying specialist agent(s) to Cloud Run (sequential): {names}")
    print("=" * 70 + "\n")

    # Pre-create the Artifact Registry repository
    print("⏳ Pre-creating Artifact Registry repository...")
    _, _, ar_err = await run_command_async([
        GCLOUD_CMD, "artifacts", "repositories", "create", "cloud-run-source-deploy",
        "--repository-format=docker",
        f"--location={region}",
        f"--project={project_id}",
        "--quiet",
    ])
    if ar_err and "ALREADY_EXISTS" not in ar_err:
        print(f"   Warning: {ar_err.strip()}")
    else:
        print("   ✓ Artifact Registry repository ready\n")

    agent_urls = {}
    failed = []

    for i, agent in enumerate(agents, 1):
        print(f"[{i}/{len(agents)}] ", end="", flush=True)
        try:
            url = await deploy_single_agent(agent, project_id, region)
            if url:
                agent_urls[agent["name"]] = url
            else:
                failed.append(agent["name"])
        except Exception as e:
            print(f"⚠️  {agent['name']} raised an error: {e}")
            failed.append(agent["name"])

    print("\n" + "=" * 70)
    print(f"Deployment complete: {len(agent_urls)}/{len(agents)} agent(s) deployed")
    print("=" * 70)

    if agent_urls:
        print("\nDeployed:")
        for name, url in agent_urls.items():
            print(f"  ✓ {name}: {url}")

        # Run comprehensive GCS and IAM permission grant pass
        await grant_all_storage_and_iam_permissions(project_id, region, list(agent_urls.keys()))

    if failed:
        print("\nFailed (re-run to retry):")
        for name in failed:
            print(f"  ❌ {name}")

    print()
    return agent_urls


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments, allowing a subset of agents to be deployed."""
    valid_names = [agent["name"] for agent in AGENTS]
    parser = argparse.ArgumentParser(
        description="Deploy specialist agents to Cloud Run."
    )
    parser.add_argument(
        "--agent",
        "-a",
        dest="agents",
        action="append",
        choices=valid_names,
        metavar="AGENT",
        help=(
            "Deploy only this agent instead of all of them. "
            f"Choices: {', '.join(valid_names)}. "
            "May be passed multiple times to deploy several specific agents."
        ),
    )
    return parser.parse_args()


async def main_async():
    """Async main function"""
    args = _parse_args()
    selected_agents = AGENTS
    if args.agents:
        selected_names = set(args.agents)
        selected_agents = [agent for agent in AGENTS if agent["name"] in selected_names]

    if selected_agents == AGENTS:
        print("Multi-Agent Cloud Run Deployment\n")
    else:
        names = ", ".join(agent["name"] for agent in selected_agents)
        print(f"Cloud Run Deployment ({names})\n")

    # Load environment configuration
    config = env_utils.load_env_file()

    try:
        env_utils.validate_required_vars(config)
    except ValueError as e:
        print(f"Error: {e}")
        print("\nPlease set the required environment variables in .env file:")
        print("  GCP_PROJECT_ID - Your Google Cloud project ID")
        print("  GCP_REGION - Deployment region (default: us-central1)")
        sys.exit(1)

    project_id = config["PROJECT_ID"]
    region = config["REGION"]

    print(f"Project: {project_id}")
    print(f"Region: {region}\n")

    # Check if gcloud is installed
    try:
        returncode, _, _ = await run_command_async([GCLOUD_CMD, "version"])
        if returncode != 0:
            raise FileNotFoundError
    except FileNotFoundError:
        print("Error: gcloud CLI not found")
        print("Please install from: https://cloud.google.com/sdk/docs/install")
        sys.exit(1)

    # Deploy the selected agents
    try:
        agent_urls = await deploy_all_agents(project_id, region, selected_agents)

        if not agent_urls:
            print("\n❌ No agents were deployed successfully")
            sys.exit(1)

        # Update .env in-place with Cloud Run URLs (replaces localhost values)
        env_utils.update_env_file_with_urls(agent_urls)

        if selected_agents == AGENTS:
            print("\n✓ All specialist agents are ready!")
        else:
            print(f"\n✓ Selected specialist agent(s) are ready: {', '.join(agent_urls.keys())}")
        print("  URLs written to .env")

        return agent_urls

    except Exception as e:
        print(f"\n❌ Error during deployment: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def main():
    """Main entry point"""
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\nDeployment interrupted. Already-deployed agents were not affected.")
        print("Re-run the script to deploy the remaining agents.")
        sys.exit(1)


if __name__ == "__main__":
    main()
