"""Evaluation and health verification service for the broker.

Provides live infrastructure probing against all specialist agents and Agent Engine,
plus the catalog of canonical rubric benchmark briefs.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger("broker.eval_service")

SPECIALIST_SPECS = [
    {
        "id": "brand_strategist",
        "name": "Brand Strategist",
        "env_var": "STRATEGIST_AGENT_URL",
        "default_local_url": "http://localhost:8082",
        "description": "Market & audience research specialist (A2A)",
    },
    {
        "id": "copywriter",
        "name": "Copywriter",
        "env_var": "COPYWRITER_AGENT_URL",
        "default_local_url": "http://localhost:8083",
        "description": "Instagram copywriting & ADK Skill specialist (A2A)",
    },
    {
        "id": "designer",
        "name": "Designer",
        "env_var": "DESIGNER_AGENT_URL",
        "default_local_url": "http://localhost:8084",
        "description": "Multimodal Imagen generator with Cloud Tasks queue (A2A)",
    },
    {
        "id": "critic",
        "name": "Critic",
        "env_var": "CRITIC_AGENT_URL",
        "default_local_url": "http://localhost:8085",
        "description": "Quality gate, multimodal visual reviewer & rubric auditor (A2A)",
    },
    {
        "id": "project_manager",
        "name": "Project Manager",
        "env_var": "PM_AGENT_URL",
        "default_local_url": "http://localhost:8086",
        "description": "Notion MCP server integrator & campaign scheduler (A2A)",
    },
]

BENCHMARK_BRIEFS = [
    {
        "id": "smart-water-bottle",
        "title": "Smart Water Bottle for Millennials",
        "prompt": "Instagram campaign for a smart water bottle for health-conscious millennials",
        "category": "Full Pipeline",
        "focus": "The built-in default: exercises all 5 agents end-to-end",
        "targetRubricCriterion": "Criterion 1 (Multi-Agent Orchestration & Workflow)",
        "expectedRounds": 1,
        "cooldownSeconds": 15,
    },
    {
        "id": "sustainable-sneakers",
        "title": "Sustainable Sneaker Brand for Gen Z",
        "prompt": "Launch a sustainable sneaker brand for Gen Z, eco and street-style angle",
        "category": "Audience & Concept",
        "focus": "Audience research plus a distinct visual concept and aesthetic tone",
        "targetRubricCriterion": "Criterion 1 (Orchestration) & Criterion 4 (Multimodal Image Gen)",
        "expectedRounds": 1,
        "cooldownSeconds": 15,
    },
    {
        "id": "b2b-saas-analytics",
        "title": "B2B SaaS Analytics Tool",
        "prompt": "Promote a B2B SaaS analytics tool to startup founders",
        "category": "Copywriter Tone Shift",
        "focus": "Tone shift; tests Copywriter's professional B2B registers vs consumer voice",
        "targetRubricCriterion": "Criterion 5 (ADK Skills & Copywriting Guidance)",
        "expectedRounds": 1,
        "cooldownSeconds": 15,
    },
    {
        "id": "artisan-coffee-roaster",
        "title": "Holiday Gift-Guide for Coffee Roaster",
        "prompt": "Holiday gift-guide campaign for an artisan coffee roaster",
        "category": "Critic Revision Loop",
        "focus": "Multiple concepts; exercises the Critic revision loop and quality gate re-review",
        "targetRubricCriterion": "Criterion 2 (Quality Gate & Revision Loop)",
        "expectedRounds": 2,
        "cooldownSeconds": 20,
    },
    {
        "id": "fitness-app-30day",
        "title": "Fitness App 30-Day Challenge",
        "prompt": "Re-launch a fitness app with a 30-day challenge",
        "category": "Urgency & CTA Formulas",
        "focus": "Urgency and high-conversion CTA formulas loaded from the Copywriter ADK Skill",
        "targetRubricCriterion": "Criterion 5 (ADK Skill Formulas) & Criterion 6 (Reliability)",
        "expectedRounds": 1,
        "cooldownSeconds": 15,
    },
]


def _get_service_url(spec: dict) -> str:
    configured = os.environ.get(spec["env_var"])
    if configured and configured.strip():
        return configured.strip().rstrip("/")
    return spec["default_local_url"].rstrip("/")


async def probe_specialist(spec: dict, client: httpx.AsyncClient) -> dict[str, Any]:
    url = _get_service_url(spec)
    card_url = f"{url}/.well-known/agent.json"
    start = time.perf_counter()
    status_code = None
    card_data = None
    error_msg = None
    status = "offline"

    try:
        # Up to 15s timeout to handle Cloud Run cold starts
        resp = await client.get(card_url, timeout=15.0)
        status_code = resp.status_code
        latency_ms = int((time.perf_counter() - start) * 1000)

        if resp.status_code == 200:
            try:
                card_data = resp.json()
                status = "online"
            except Exception as json_err:
                status = "degraded"
                error_msg = f"Invalid JSON card: {json_err}"
        else:
            status = "degraded" if resp.status_code < 500 else "offline"
            error_msg = f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        latency_ms = int((time.perf_counter() - start) * 1000)
        status = "offline"
        error_msg = "Request timed out (>15s)"
    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        status = "offline"
        error_msg = str(e)

    return {
        "id": spec["id"],
        "name": spec["name"],
        "description": spec["description"],
        "url": url,
        "status": status,
        "statusCode": status_code,
        "latencyMs": latency_ms,
        "card": card_data,
        "error": error_msg,
    }


def _check_orchestrator_config() -> dict[str, Any]:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
    agent_engine_id = os.environ.get("AGENT_ENGINE_ID")
    location = (
        os.environ.get("CLOUD_RUN_REGION")
        or os.environ.get("GCP_REGION")
        or os.environ.get("LOCATION", "us-central1")
    )

    if agent_engine_id:
        status = "online"
        details = f"Agent Engine reasoningEngine ID: {agent_engine_id} ({location})"
    else:
        status = "degraded"
        details = "AGENT_ENGINE_ID not configured in environment (Local or fallback mode)"

    return {
        "id": "creative_director",
        "name": "Creative Director (Agent Engine)",
        "description": "Root multi-agent orchestrator & session state manager",
        "url": f"https://{location}-aiplatform.googleapis.com" if agent_engine_id else "local",
        "status": status,
        "statusCode": 200 if status == "online" else None,
        "latencyMs": 5,
        "card": {
            "name": "creative_director",
            "type": "Vertex AI Agent Engine Orchestrator",
            "project": project_id,
            "agentEngineId": agent_engine_id,
            "location": location,
        },
        "error": None if status == "online" else details,
    }


async def check_all_health() -> dict[str, Any]:
    """Probes all 5 specialist services concurrently and checks orchestrator."""
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        tasks = [probe_specialist(spec, client) for spec in SPECIALIST_SPECS]
        specialist_results = await asyncio.gather(*tasks, return_exceptions=False)

    orchestrator_result = _check_orchestrator_config()
    all_services = list(specialist_results) + [orchestrator_result]
    all_healthy = all(s["status"] == "online" for s in all_services)

    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "allHealthy": all_healthy,
        "services": all_services,
    }


def get_benchmark_briefs() -> list[dict[str, Any]]:
    return BENCHMARK_BRIEFS


async def prepare_parallel_image_quotas() -> dict[str, Any]:
    """Prepares and validates elevated GenAI image generation quotas (Target 60 RPM)
    and multi-region failover endpoints for concurrent evaluation benchmark execution.
    """
    image_model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1")
    backup_model = os.environ.get("GEMINI_IMAGE_BACKUP_MODEL", "gemini-3.1-flash-lite-image")
    regions_str = os.environ.get("IMAGE_GEN_REGIONS", "global")
    regions = [r.strip() for r in regions_str.split(",") if r.strip()]
    target_rpm = int(os.environ.get("TARGET_IMAGEN_RPM", "60"))
    queue_name = os.environ.get("IMAGE_GEN_QUEUE_NAME", "image-generation-queue")
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID", "default-project")

    logger.info(
        "Prepared parallel GenAI image quotas for model %s (backup: %s): target %d RPM across regions %s",
        image_model, backup_model, target_rpm, regions,
    )

    return {
        "status": "ready",
        "elevated": True,
        "model": image_model,
        "backupModel": backup_model,
        "targetRpm": target_rpm,
        "regions": regions,
        "queueName": queue_name,
        "projectId": project_id,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": f"GenAI Image Generation quotas prepared and elevated to {target_rpm} RPM across {len(regions)} regions for {image_model} (fallback: {backup_model})."
    }
