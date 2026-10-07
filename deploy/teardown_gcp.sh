#!/bin/bash

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

# Teardown script for AI Creative Studio
# Deletes all Cloud Run services, Cloud Tasks queues, service accounts, Secret Manager secrets, build staging buckets, and the Agent Engine resource
# Usage:
#   bash deploy/teardown_gcp.sh                # Keeps campaign images bucket (default)
#   bash deploy/teardown_gcp.sh --keep-images  # Explicitly keep images bucket
#   bash deploy/teardown_gcp.sh --delete-images# Also delete the campaign images bucket
#   bash deploy/teardown_gcp.sh -y             # Non-interactive confirmation

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Default options
DELETE_IMAGES=false
CONFIRM_YES=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --delete-images)
            DELETE_IMAGES=true
            shift
            ;;
        --keep-images)
            DELETE_IMAGES=false
            shift
            ;;
        -y|--yes|--force)
            CONFIRM_YES=true
            shift
            ;;
        -h|--help)
            echo "Usage: bash deploy/teardown_gcp.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --keep-images       Preserve the campaign images bucket (default)"
            echo "  --delete-images     Also delete the campaign images bucket"
            echo "  -y, --yes, --force  Skip interactive confirmation prompt"
            echo "  -h, --help          Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Run 'bash deploy/teardown_gcp.sh --help' for usage."
            exit 1
            ;;
    esac
done

# Load .env if present
ENV_FILE="$(dirname "$0")/../.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-${GCP_PROJECT_ID:-${PROJECT_ID:-}}}"
if [ -z "$PROJECT_ID" ]; then
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null || true)
fi

REGION="${CLOUD_RUN_REGION:-${GCP_REGION:-${LOCATION:-${REGION:-us-central1}}}}"
TASKS_LOCATION="${CAMPAIGN_TASKS_LOCATION:-${GCP_TASKS_LOCATION:-${IMAGE_GEN_TASKS_LOCATION:-$REGION}}}"
IMAGES_BUCKET="${GCS_IMAGES_BUCKET:-${PROJECT_ID}-campaign-images}"

# Resolve Agent Engine identifier
AGENT_ENGINE_RESOURCE_NAME="${AGENT_ENGINE_RESOURCE_NAME:-}"
if [ -z "$AGENT_ENGINE_RESOURCE_NAME" ] && [ -n "${AGENT_ENGINE_ID:-}" ]; then
    AGENT_ENGINE_RESOURCE_NAME="projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${AGENT_ENGINE_ID}"
fi

echo -e "${RED}=== AI Creative Studio — GCP Teardown ===${NC}\n"

# Validate gcloud
if ! command -v gcloud &>/dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed${NC}"
    exit 1
fi

# Prompt for project ID if not set
if [ -z "$PROJECT_ID" ]; then
    echo -e "${YELLOW}Enter your GCP Project ID:${NC}"
    read -r PROJECT_ID
fi

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: Project ID is required${NC}"
    exit 1
fi

SERVICES=(
    "brand-strategist"
    "copywriter"
    "designer"
    "critic"
    "project-manager"
    "broker"
    "campaign-driver"
    "creative-director-ui"
)

IMAGE_GEN_QUEUE="${IMAGE_GEN_TASKS_QUEUE:-image-generation}"
CAMPAIGN_QUEUE="${CAMPAIGN_TASKS_QUEUE:-campaigns}"
QUEUES=("$IMAGE_GEN_QUEUE" "$CAMPAIGN_QUEUE")

SERVICE_ACCOUNTS=(
    "broker-sa"
    "campaign-driver-sa"
    "campaign-tasks-invoker"
    "image-gen-tasks-invoker"
)

SECRETS=(
    "notion-token"
    "notion-project-db-id"
    "notion-tasks-db-id"
)

echo -e "${YELLOW}The following resources will be deleted:${NC}"
echo -e "  Cloud Run services (${#SERVICES[@]}): ${SERVICES[*]}"
echo -e "  Cloud Tasks queues (${#QUEUES[@]} in $TASKS_LOCATION): ${QUEUES[*]}"
echo -e "  Dedicated Service Accounts (${#SERVICE_ACCOUNTS[@]}): ${SERVICE_ACCOUNTS[*]}"
echo -e "  Artifact Registry: cloud-run-source-deploy ($REGION)"
echo -e "  Firebase Hosting (Web UI): $PROJECT_ID (will be disabled)"

# Build buckets list
BUCKETS_TO_DELETE=(
    "gs://${PROJECT_ID}-agent-staging"
    "gs://run-sources-${PROJECT_ID}-${REGION}"
)

if [ "$DELETE_IMAGES" = true ]; then
    BUCKETS_TO_DELETE+=("gs://${IMAGES_BUCKET}")
    echo -e "  GCS buckets: ${BUCKETS_TO_DELETE[*]} (includes campaign images bucket)"
else
    echo -e "  GCS buckets: ${BUCKETS_TO_DELETE[*]} (${GREEN}preserving gs://${IMAGES_BUCKET}${YELLOW})"
fi

echo -e "  Secret Manager secrets: ${SECRETS[*]} (if present)"
if [ -n "$AGENT_ENGINE_RESOURCE_NAME" ]; then
    echo -e "  Agent Engine: $AGENT_ENGINE_RESOURCE_NAME"
else
    echo -e "  Agent Engine: (AGENT_ENGINE_RESOURCE_NAME / AGENT_ENGINE_ID not set — will be skipped)"
fi

if [ "$CONFIRM_YES" = true ]; then
    echo -e "\n${GREEN}Non-interactive confirmation enabled (--yes). Proceeding with teardown...${NC}"
else
    echo -e "\n${RED}This action cannot be undone!${NC}"
    echo -e "${YELLOW}Continue? (yes/no):${NC}"
    read -r CONFIRM

    if [ "$CONFIRM" != "yes" ]; then
        echo -e "${GREEN}Teardown cancelled${NC}"
        exit 0
    fi
fi

gcloud config set project "$PROJECT_ID" --quiet

# ─── Delete Cloud Run services ────────────────────────────────────────────────
echo -e "\n${YELLOW}Deleting Cloud Run services...${NC}"

for SVC in "${SERVICES[@]}"; do
    if gcloud run services describe "$SVC" \
        --region="$REGION" \
        --project="$PROJECT_ID" &>/dev/null; then
        gcloud run services delete "$SVC" \
            --region="$REGION" \
            --project="$PROJECT_ID" \
            --quiet
        echo -e "  ${GREEN}✓ Deleted: $SVC${NC}"
    else
        echo -e "  ${YELLOW}Not found, skipping: $SVC${NC}"
    fi
done

# ─── Delete Cloud Tasks queues ────────────────────────────────────────────────
echo -e "\n${YELLOW}Deleting Cloud Tasks queues...${NC}"

for QUEUE in "${QUEUES[@]}"; do
    if gcloud tasks queues describe "$QUEUE" \
        --location="$TASKS_LOCATION" \
        --project="$PROJECT_ID" &>/dev/null; then
        gcloud tasks queues delete "$QUEUE" \
            --location="$TASKS_LOCATION" \
            --project="$PROJECT_ID" \
            --quiet
        echo -e "  ${GREEN}✓ Deleted queue: $QUEUE ($TASKS_LOCATION)${NC}"
    else
        echo -e "  ${YELLOW}Not found, skipping queue: $QUEUE ($TASKS_LOCATION)${NC}"
    fi
done

# ─── Delete Dedicated Service Accounts ────────────────────────────────────────
echo -e "\n${YELLOW}Deleting Dedicated Service Accounts...${NC}"

for SA in "${SERVICE_ACCOUNTS[@]}"; do
    SA_EMAIL="${SA}@${PROJECT_ID}.iam.gserviceaccount.com"
    if gcloud iam service-accounts describe "$SA_EMAIL" \
        --project="$PROJECT_ID" &>/dev/null; then
        gcloud iam service-accounts delete "$SA_EMAIL" \
            --project="$PROJECT_ID" \
            --quiet
        echo -e "  ${GREEN}✓ Deleted service account: $SA_EMAIL${NC}"
    else
        echo -e "  ${YELLOW}Not found, skipping service account: $SA_EMAIL${NC}"
    fi
done

# ─── Delete Agent Engine ───────────────────────────────────────────────────────
echo -e "\n${YELLOW}Deleting Agent Engine...${NC}"

if [ -z "$AGENT_ENGINE_RESOURCE_NAME" ]; then
    echo -e "  ${YELLOW}AGENT_ENGINE_RESOURCE_NAME / AGENT_ENGINE_ID not set — skipping Agent Engine deletion${NC}"
else
    PROJECT_ID="$PROJECT_ID" REGION="$REGION" AGENT_ENGINE_RESOURCE_NAME="$AGENT_ENGINE_RESOURCE_NAME" python - <<PYEOF
import os, sys
try:
    import vertexai
except ImportError:
    print("  vertexai not installed — skipping Agent Engine deletion")
    sys.exit(0)

project  = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID", "")
location = os.environ.get("REGION") or os.environ.get("CLOUD_RUN_REGION") or os.environ.get("GCP_REGION") or os.environ.get("LOCATION", "us-central1")
resource = os.environ.get("AGENT_ENGINE_RESOURCE_NAME", "")
agent_id = os.environ.get("AGENT_ENGINE_ID", "")

if not resource and agent_id:
    resource = f"projects/{project}/locations/{location}/reasoningEngines/{agent_id}"

if not resource:
    print("  AGENT_ENGINE_RESOURCE_NAME not set — skipping")
    sys.exit(0)

try:
    client = vertexai.Client(project=project, location=location)
    client.agent_engines.delete(name=resource, force=True)
    print(f"  ✓ Agent Engine deleted: {resource}")
except Exception as e:
    print(f"  Warning: could not delete Agent Engine: {e}")
    print(f"  Delete manually: https://console.cloud.google.com/vertex-ai/reasoning-engines?project={project}")
PYEOF
fi

# ─── Delete Artifact Registry repository ─────────────────────────────────────
echo -e "\n${YELLOW}Deleting Artifact Registry repository...${NC}"

if gcloud artifacts repositories describe cloud-run-source-deploy \
    --location="$REGION" \
    --project="$PROJECT_ID" &>/dev/null; then
    gcloud artifacts repositories delete cloud-run-source-deploy \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --quiet
    echo -e "  ${GREEN}✓ Deleted: cloud-run-source-deploy${NC}"
else
    echo -e "  ${YELLOW}Not found, skipping: cloud-run-source-deploy${NC}"
fi

# ─── Delete GCS buckets ─────────────────────��─────────────────────────────────
echo -e "\n${YELLOW}Deleting GCS buckets...${NC}"

for BUCKET in "${BUCKETS_TO_DELETE[@]}"; do
    if gcloud storage buckets describe "$BUCKET" --project="$PROJECT_ID" &>/dev/null; then
        gcloud storage rm -r "$BUCKET" --quiet
        echo -e "  ${GREEN}✓ Deleted: $BUCKET${NC}"
    else
        echo -e "  ${YELLOW}Not found, skipping: $BUCKET${NC}"
    fi
done

# ─── Delete Secret Manager secrets ───────────────────────────────────────────
echo -e "\n${YELLOW}Deleting Secret Manager secrets (Notion credentials)...${NC}"

for SECRET in "${SECRETS[@]}"; do
    if gcloud secrets describe "$SECRET" --project="$PROJECT_ID" &>/dev/null; then
        gcloud secrets delete "$SECRET" --project="$PROJECT_ID" --quiet
        echo -e "  ${GREEN}✓ Deleted: $SECRET${NC}"
    else
        echo -e "  ${YELLOW}Not found, skipping: $SECRET${NC}"
    fi
done

# ─── Disable Firebase Hosting (Web UI) ─────────────────────────────────────────
if command -v firebase &>/dev/null; then
    echo -e "\n${YELLOW}Disabling Firebase Hosting (Web UI)...${NC}"
    if firebase hosting:disable --project="$PROJECT_ID" --force &>/dev/null; then
        echo -e "  ${GREEN}✓ Disabled Firebase Hosting for: $PROJECT_ID${NC}"
    else
        echo -e "  ${YELLOW}Firebase Hosting not configured or already disabled, skipping${NC}"
    fi
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}=== Teardown Complete ===${NC}"
echo -e "\nVerify remaining resources:"
echo -e "  gcloud run services list --region=$REGION"
echo -e "  gcloud tasks queues list --location=$TASKS_LOCATION"
echo -e "  gcloud iam service-accounts list --project=$PROJECT_ID"
echo -e "  gcloud storage buckets list --project=$PROJECT_ID"
echo -e "  https://console.cloud.google.com/vertex-ai/reasoning-engines?project=$PROJECT_ID"
echo -e "  https://console.firebase.google.com/project/$PROJECT_ID/hosting"
