#!/usr/bin/env python3
"""
Deploy Gradio Frontend to Cloud Run.
"""

import os
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Add project root to path for env_utils
deploy_dir = Path(__file__).parent
sys.path.insert(0, str(deploy_dir))

try:
    import env_utils
except ImportError:
    print("Error: Could not import env_utils. Make sure you are running from the project root or deploy/ folder.")
    sys.exit(1)

GCLOUD_CMD = "gcloud.cmd" if os.name == "nt" else "gcloud"

def deploy_gradio():
    # Load environment
    config = env_utils.load_env_file()
    try:
        env_utils.validate_required_vars(config)
    except ValueError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    
    project_id = config["PROJECT_ID"]
    region = config["REGION"]
    project_number = os.getenv("GOOGLE_CLOUD_PROJECT_NUMBER")
    
    # Gradio specific variables from .env
    # We use os.getenv to get all loaded vars
    agent_engine_id = os.getenv("AGENT_ENGINE_ID")
    gcs_bucket = os.getenv("GCS_IMAGES_BUCKET")
    signing_sa = os.getenv("SIGNING_SERVICE_ACCOUNT")
    
    print(f"Deploying Gradio UI to Cloud Run in {region}...")
    print(f"   Project ID: {project_id}")
    print(f"   Project Number: {project_number}")
    print(f"   Region: {region}")
    print(f"   Engine ID: {agent_engine_id}")
    print(f"   GCS Bucket: {gcs_bucket}")
    print(f"   Signing SA: {signing_sa}")
    
    gradio_dir = Path(__file__).parent.parent / "gradio-ui"
    
    # Build environment variables for Cloud Run
    env_vars = [
        f"GOOGLE_CLOUD_PROJECT={project_id}",
        f"LOCATION={region}",
        f"AGENT_MODE=remote",
    ]
    
    if project_number:
        env_vars.append(f"GOOGLE_CLOUD_PROJECT_NUMBER={project_number}")
    if agent_engine_id:
        env_vars.append(f"AGENT_ENGINE_ID={agent_engine_id}")
    if gcs_bucket:
        env_vars.append(f"GCS_IMAGES_BUCKET={gcs_bucket}")
    if signing_sa:
        env_vars.append(f"SIGNING_SERVICE_ACCOUNT={signing_sa}")
        
    env_vars_str = ",".join(env_vars)
    
    cmd = [
        GCLOUD_CMD, "run", "deploy", "creative-director-ui",
        "--source=.",
        "--port=8080",
        "--platform=managed",
        f"--region={region}",
        f"--project={project_id}",
        "--allow-unauthenticated",
        f"--set-env-vars={env_vars_str}",
        "--memory=2Gi",
        "--cpu=1",
        "--timeout=300",
        "--quiet"
    ]
    
    print(f"   Command: {' '.join(cmd)}")
    
    # Run deployment
    try:
        result = subprocess.run(cmd, cwd=gradio_dir)
        if result.returncode == 0:
            print("\n✅ Gradio UI deployed successfully!")
        else:
            print(f"\n❌ Failed to deploy Gradio UI (exit code {result.returncode})")
            sys.exit(result.returncode)
                
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    deploy_gradio()
