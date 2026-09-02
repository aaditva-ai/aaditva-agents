---
sessionId: session-260901-153118-2fjj
---

# Requirements

### Overview & Goals
The goal of this feature is to introduce a dedicated **Evaluation Dashboard** into the Aaditva Multi-Agent Creative Studio Web UI. This allows evaluators, graders, and operators to interactively verify that the project satisfies 100% of the Capstone Grading Rubric (`EVALUATION.md`).

The main campaign creation and monitoring flow will remain the core experience on `/`, while a new **Evaluation** view accessible from the top navigation menu provides:
1. **Live Infrastructure & Agent Card Verification**: Instant health checks and `/.well-known/agent.json` inspection across all 5 specialist Cloud Run services and the Agent Engine Orchestrator.
2. **Curated Rubric Benchmark Briefs**: Quick-launch canonical prompts specifically designed to exercise every rubric capability (full pipeline, audience research, copywriter tone shift, multi-concept critic revision loop, and urgency CTA formulas).
3. **Flexible Execution Engine (Parallel & Sequential Modes)**: 
   - **Parallel Eval Mode**: Runs benchmark campaigns concurrently with elevated Vertex AI Image generation quotas (with automated Cloud Quotas API setup / `gcloud` helper scripts and Cloud Tasks retryable backoff resilience).
   - **Sequential / Spaced Mode**: Paced fallback execution with cooldown safety margins for standard quota tiers.
4. **LLM-as-a-Judge Rubric Auditor**: Automated evaluation system powered by Gemini that assesses completed campaign transcripts against the 7 grading criteria (100% scale), generating transparent scorecards and qualitative evidence.
5. **Token & Spend Efficiency**: Conservative status checking (~5-minute intervals) avoiding excessive log/endpoint polling that wastes LLM tokens and AI spend during 7–10 minute campaign execution lifecycles.

---

### Scope
#### In Scope
- **Top Navigation Menu**: Add clear tabbed navigation in `web/src/components/Layout.tsx` linking between "Campaigns" (`/`) and "Evaluation" (`/evaluation`).
- **Service & Agent Card Health Probing**:
  - Probes Brand Strategist, Copywriter, Designer, Critic, Project Manager, and Creative Director.
  - Displays endpoint URLs, HTTP status, cold-start latency, and parsed A2A agent card metadata.
- **Benchmark Briefs Catalog & Parallel/Sequential Eval Runner**:
  - Interactive cards for the 5 key test briefs specified in the rubric.
  - Multi-mode eval runner supporting **Parallel Mode** (concurrent brief executions enabled via Vertex AI image generation quota scaling) and **Sequential Mode** (cooldown-spaced pacing).
  - Vertex AI quota setup script/guidance (`deploy/setup_vertex_quotas.sh` using GCP Cloud Quotas API / `gcloud quotas preferences create`) to elevate Imagen RPM/TPM limits for parallel runs.
- **LLM-as-a-Judge Engine**:
  - Starlette backend service endpoint (`POST /evals/judge`) evaluating campaign outputs against the 7 criteria defined in `EVALUATION.md` upon completion.
  - Rich frontend scorecard visualizing Criterion 1 (20%), Criterion 2 (20%), Criterion 3 (15%), Criterion 4 (15%), Criterion 5 (10%), Criterion 6 (10%), Criterion 7 (10%).
- **Campaign-Level Evaluation Trigger & Conservative Polling**:
  - Evaluate button on campaign transcript pages allowing on-demand rubric scoring of completed runs.
  - Conservative polling strategy (~5-minute cadence or terminal-state checks) avoiding frequent probing of cloud logs/endpoints that wastes agent tokens and AI spend.

#### Out of Scope
- Modifying the core A2A protocol or existing specialist agent prompts (the agents already meet the 100% rubric standard; this feature builds the demo and verification UI/eval system).
- External synthetic load testing or DDoS simulation.

---

### User Stories
- **As an Evaluator/Grader**, I want to navigate to the Evaluation page and run a health check so that I can immediately confirm all 5 specialist Cloud Run services are online with valid A2A agent cards.
- **As an Evaluator/Grader**, I want to select a pre-configured rubric brief (such as the Critic Revision Loop brief) and run it with one click so that I can see the multi-agent pipeline exercise that specific rubric criterion.
- **As an Operator/Reviewer**, I want to trigger an automated LLM judge on completed campaigns so that I can verify objective compliance with each of the 7 rubric criteria and review structured scoring rationales.

---

### Functional Requirements
1. **Navigation**: Top header must present active route indicators for "Campaigns" and "Evaluation".
2. **Live Health & Card Inspector**:
   - "Check Health" button triggers parallel checks against all agent endpoints.
   - Shows badge status: `Online` (green), `Degraded` (amber), `Offline` (red), along with response times.
   - Allows expanding any agent card to inspect advertised endpoints, skills, and tools in JSON format.
3. **Pre-Determined Rubric Prompts & Multi-Mode Eval Runner**:
   - Renders a responsive grid of the 5 canonical briefs with clear badges indicating the target rubric exercise.
   - Supports 1-click single launching, **Parallel Eval Mode** (runs all 5 benchmarks concurrently leveraging elevated Vertex AI image generation quotas), and **Sequential Eval Mode** (paced runs with cooldown buffer).
   - In Parallel Mode, concurrent Designer image generations leverage the existing Cloud Tasks backoff queue and Firestore job store with exponential backoff on transient 429 quota spikes.
4. **LLM-as-a-Judge Evaluation**:
   - Backend evaluates transcripts using Gemini with a structured rubric evaluation prompt once terminal completion is reached.
   - Stores evaluation results in Firestore under `campaigns/{sessionId}/evaluation`.
   - Displays weighted scores (total out of 100%), criterion-by-criterion breakdown, pass/fail status, and explanation for each criterion.

### Non-Functional Requirements
1. **Quota & Rate Limit Protection**: Prevents concurrent image generation bursts on Vertex AI by strictly serializing multi-eval runs and respecting cooldown intervals.
2. **Token & Spend Efficiency**: Campaign monitoring uses conservative polling (~5-minute checking intervals / event-driven updates) rather than aggressive log polling, preventing unnecessary AI token expenditure during multi-minute runs.

# Technical Design

### Current Implementation
- **Frontend (`web/`)**: React 19 SPA with Vite, Tailwind CSS v4, React Router v7, and TanStack Query v5. The current layout in `web/src/components/Layout.tsx` renders a single header logo linking to `/`.
- **Backend (`broker/`)**: Starlette application running on Cloud Run or locally. Routes include `POST /campaigns`, `GET /campaigns`, `GET /campaigns/{id}/events`, `POST /campaigns/{id}/resume`.
- **Verification Scripts (`deploy/verify_agent_cards.py`)**: Standalone Python script validating `/.well-known/agent.json` on local ports (8082–8086) or Cloud Run HTTPS endpoints.

---

### Architecture & Data Flow

```mermaid
graph TD
    User([Evaluator / User]) -->|Browser Navigation| SPA[React SPA - Web UI]
    
    subgraph Frontend [React SPA (web/)]
        Nav[Layout Header Navigation]
        EvalPage[EvaluationRoute /evals]
        HealthComp[AgentHealthGrid]
        BriefsComp[BenchmarkBriefsCard]
        JudgeComp[JudgeScorecard]
        CampaignPage[CampaignRoute /c/:sessionId]
    end
    
    SPA --> Nav
    Nav --> EvalPage
    Nav --> CampaignPage
    EvalPage --> HealthComp
    EvalPage --> BriefsComp
    EvalPage --> JudgeComp
    
    subgraph Backend [Starlette Broker (broker/)]
        HealthRoute[GET /evals/health]
        JudgeRoute[POST /evals/judge]
        EvalService[eval_service.py]
        JudgeService[judge_service.py (Gemini 2.5 Flash)]
    end
    
    HealthComp -->|authedFetch| HealthRoute
    JudgeComp -->|authedFetch| JudgeRoute
    CampaignPage -->|Trigger Judge| JudgeRoute
    
    HealthRoute --> EvalService
    JudgeRoute --> JudgeService
    
    subgraph Specialists [A2A Specialist Services]
        S1[Brand Strategist :8082]
        S2[Copywriter :8083]
        S3[Designer :8084]
        S4[Critic :8085]
        S5[Project Manager :8086]
    end
    
    EvalService -->|Fetch /.well-known/agent.json| Specialists
    JudgeService -->|Read Transcript & Store Eval| Firestore[(Firestore DB)]
    JudgeService -->|Run Rubric Eval Prompt| VertexAI[(Vertex AI Gemini)]
```

---

### Key Decisions
1. **Unified Broker Endpoints vs Direct Client Probes**: Broker handles agent card polling and LLM judge orchestration. This avoids browser CORS limitations when probing remote Cloud Run endpoints directly from client-side JS, keeps Vertex AI credentials secure on the backend, and centralizes Firestore evaluation caching.
2. **Dual-Mode Health Check**: `eval_service.py` detects whether it is in deployed mode (using environment variables `STRATEGIST_AGENT_URL`, etc.) or local mode, providing accurate health and agent card details in both environments.
3. **LLM-as-a-Judge Prompt Design**: Implements a strict JSON schema evaluator based directly on the 7 criteria in `EVALUATION.md`. The prompt assesses orchestrator sequence, critic revision loops, multimodal review, image generation, skill/MCP usage, retry resilience, and overall delivery quality.
4. **Vertex AI Quota Escalation & Parallel Eval Orchestration**:
   - GCP Vertex AI Imagen quotas (default ~5–10 requests/minute) can cause `RESOURCE_EXHAUSTED` errors during concurrent runs. We provide a setup script (`deploy/setup_vertex_quotas.sh`) leveraging GCP Cloud Quotas API (`gcloud alpha quotas preferences create` / Cloud Quotas REST API) to temporarily request increased quota for the project (e.g., target 60 RPM for `aiplatform.googleapis.com/generate_content_requests_per_minute_per_project_per_base_model` / Imagen endpoints).
   - The Eval UI provides a toggle between **Parallel Mode** (runs all 5 rubric briefs concurrently) and **Sequential Mode** (spaces runs with cooldowns).
   - Parallel runs benefit from Designer's decoupled Cloud Tasks queue (`IMAGE_GEN_QUEUE_NAME`), which retries transient rate limits with exponential backoff while keeping the UI responsive.
5. **Token & Spend Conservation in Polling**: Because campaigns take 7–10 minutes to run end-to-end, automated probing against cloud logs or broker endpoints is paced conservatively (e.g., status verification check every 5 minutes during in-flight evaluation runs, only running the LLM-as-a-Judge prompt once upon final campaign completion) to minimize AI spend and unnecessary token consumption.

---

### Data Models / Contracts

#### Broker API Contracts

**`GET /evals/health` Response:**
```json
{
  "timestamp": "2025-05-10T12:00:00Z",
  "allHealthy": true,
  "services": [
    {
      "id": "brand_strategist",
      "name": "Brand Strategist",
      "url": "https://brand-strategist-xxx.run.app",
      "status": "online",
      "statusCode": 200,
      "latencyMs": 142,
      "card": {
        "name": "brand_strategist",
        "description": "...",
        "url": "https://brand-strategist-xxx.run.app"
      }
    }
  ]
}
```

**`POST /evals/judge` Request & Response:**
```json
// Request
{
  "sessionId": "b8a514d3-e722-4a0b-9df0-7612f0088921"
}

// Response
{
  "sessionId": "b8a514d3-e722-4a0b-9df0-7612f0088921",
  "evaluatedAt": "2025-05-10T12:05:00Z",
  "overallScore": 100.0,
  "overallGrade": "Excellent",
  "criteria": [
    {
      "id": 1,
      "name": "Multi-Agent Orchestration & Workflow",
      "weight": 0.20,
      "score": 100,
      "rating": "Excellent",
      "passed": true,
      "rationale": "Orchestrator cleanly executed Brand Strategist -> Copywriter -> Designer -> Critic -> PM in strict sequence with contextual enrichment.",
      "evidence": ["Brand Strategist produced target demographics", "Copywriter incorporated persona", "Designer generated matching visuals"]
    },
    {
      "id": 2,
      "name": "Quality Gate & Revision Loop",
      "weight": 0.20,
      "score": 100,
      "rating": "Excellent",
      "passed": true,
      "rationale": "Critic performed multimodal visual inspection and structured scoring. Approved status verified before PM planning.",
      "evidence": ["Critic returned POSTS REVIEW & VISUALS REVIEW", "Verdict APPROVED"]
    }
  ]
}
```

---

### File Changes & Additions

#### Backend & Deployment (`broker/` & `deploy/`)
- `broker/eval_service.py` *(new)*: Health check probes and agent card fetcher.
- `broker/judge_service.py` *(new)*: LLM-as-a-Judge execution using Vertex AI Gemini against campaign transcript history and Firestore caching.
- `broker/main.py`: Register routes `GET /evals/health`, `POST /evals/judge`, `GET /evals/benchmarks`, `GET /evals/campaigns/{sessionId}`.
- `deploy/setup_vertex_quotas.sh` *(new)*: Script using GCP Cloud Quotas API / `gcloud quotas` to request/verify elevated Vertex AI Imagen quotas for parallel benchmark execution.

#### Frontend (`web/`)
- `web/src/api/types.ts`: Add `AgentHealthReport`, `ServiceHealthItem`, `JudgeEvaluationResult`, `CriterionEval`, `BenchmarkBrief`.
- `web/src/api/queries.ts`: Add `useAgentHealth`, `useTriggerJudgeEval`, `useCampaignEvaluation`, `useBenchmarkBriefs`.
- `web/src/components/Layout.tsx`: Add navigation bar tabs (`Campaigns` vs `Evaluation Dashboard`).
- `web/src/components/evals/AgentHealthGrid.tsx` *(new)*: Grid of agent cards with latency, status indicators, and expandable JSON inspector.
- `web/src/components/evals/BenchmarkBriefsCard.tsx` *(new)*: Table/cards of 5 rubric briefs with 1-click launch, Parallel / Sequential mode toggle, and batch progress tracking.
- `web/src/components/evals/JudgeScorecard.tsx` *(new)*: Rubric breakdown showing score tiers (25/50/75/100), criterion weights, and detailed judge rationales.
- `web/src/routes/EvaluationRoute.tsx` *(new)*: Master Evaluation Dashboard route.
- `web/src/routes/CampaignRoute.tsx` & `web/src/components/TranscriptView.tsx`: Embed "Run Rubric Evaluation" button and scorecard modal/drawer.
- `web/src/App.tsx`: Add `/evaluation` route.

# Testing

### Validation Approach
Verification will ensure both the infrastructure verification features and the LLM-as-a-judge system work seamlessly in local and deployed environments.

### Key Scenarios
1. **Header Navigation**:
   - Verify clicking "Evaluation Dashboard" in `Layout.tsx` navigates to `/evaluation`.
   - Verify clicking "Aaditva Campaign Builder" or "Campaigns" navigates back to `/`.
2. **Health Check Probing**:
   - Trigger "Run Health Check" on the dashboard.
   - Verify all 5 specialist services (ports 8082–8086 locally or Cloud Run URLs in cloud mode) are queried.
   - Confirm agent card details (name, endpoints, advertised URLs) are decoded and expandable.
   - Verify handling of slow/cold-starting services with timeout resilience.
3. **Benchmark Brief 1-Click Launch & Execution Modes**:
   - Click "Launch Campaign" on each of the 5 canonical briefs (e.g. *B2B SaaS analytics tool*, *Holiday gift-guide coffee roaster*).
   - Test **Parallel Mode**: verify all 5 benchmarks launch concurrently, handle concurrent Cloud Tasks queueing without unhandled crashes, and progress independently.
   - Test **Sequential Mode**: verify single-campaign concurrency with cooldown delays between runs.
   - Verify that all active runs check completion status conservatively (~5-minute interval) to avoid token waste.
4. **LLM-as-a-Judge Evaluation & Cost/Polling Efficiency**:
   - Run a judge evaluation on a completed campaign.
   - Verify structured evaluation response conforms to the 7 rubric criteria.
   - Verify overall weighted score calculation (100% scale) and detailed criterion evidence render correctly.
   - Confirm caching in Firestore prevents unnecessary re-evaluations and verify that status polling during execution occurs conservatively (every ~5 mins) to avoid wasting tokens.

### Test Changes
- `web/src/api/queries.test.tsx`: Add tests for health check query and judge evaluation mutation.
- `web/src/components/evals/__tests__/JudgeScorecard.test.tsx`: Unit tests for scoring badge colors, progress bars, and criteria calculations.

# Delivery Steps

### ✓ Step 1: Implement broker health check, LLM-as-judge endpoints, and quota setup script
Implement the backend evaluation, health verification services, and GCP quota tooling.

- Create `broker/eval_service.py` to check agent card availability and health across all 5 specialist agents (Brand Strategist, Copywriter, Designer, Critic, Project Manager) plus Orchestrator / Agent Engine, reusing logic from `deploy/verify_agent_cards.py`.
- Implement `broker/judge_service.py` using Vertex AI Gemini to evaluate campaign transcripts against the 7 rubric criteria from `EVALUATION.md`, returning structured scores and rationales only when campaigns reach completion.
- Add broker endpoints: `GET /evals/health` for agent/service status, `POST /evals/judge` to trigger an LLM-as-a-Judge run for a campaign session, and `GET /evals/benchmarks` for canonical rubric test prompts.
- Persist judge evaluation results in Firestore under `campaigns/{sessionId}/evaluation` for fast retrieval and history display.
- Add `deploy/setup_vertex_quotas.sh` with GCP Cloud Quotas API / `gcloud` commands to check and request elevated Vertex AI Image generation quotas (Imagen RPM) for running parallel benchmarks.

### ✓ Step 2: Configure SPA routing, navigation menu, and API hooks
Build API client hooks, TypeScript types, and routing in the React SPA.

- Define TypeScript interfaces in `web/src/api/types.ts` for `AgentHealthStatus`, `RubricCriterionEval`, `JudgeEvaluationResult`, and `BenchmarkBrief`.
- Create TanStack Query hooks in `web/src/api/queries.ts` (`useAgentHealth`, `useTriggerJudgeEval`, `useCampaignEvaluation`, `useBenchmarkBriefs`).
- Update `web/src/components/Layout.tsx` with top-level navigation tabs ("Campaigns" and "Evaluation Dashboard").
- Register the `/evaluation` route in `web/src/App.tsx` mapped to `EvaluationRoute.tsx`.

### ✓ Step 3: Implement Evaluation Dashboard UI and Rubric Verification views
Build the interactive Evaluation Dashboard UI with infrastructure health, agent card viewer, benchmark briefs runner supporting both parallel and sequential execution, and LLM-as-a-judge scorecards.

- Create `web/src/components/evals/AgentHealthGrid.tsx` with live "Run Health Check" triggers, latency indicators, status badges, and expandable `agent.json` card inspector.
- Create `web/src/components/evals/BenchmarkBriefsCard.tsx` rendering the 5 canonical briefs with "Exercise Focus" badges, single-launch actions, and a toggle between **Parallel Mode** (concurrent benchmark execution with quota awareness) and **Sequential Mode** (cooldown spacing).
- Create `web/src/components/evals/JudgeScorecard.tsx` rendering the 7 rubric criteria (Criteria 1–7) with weighted scoring, criteria status (Excellent/Good/Developing/Unsatisfactory), and LLM judge feedback breakdown.
- Assemble `web/src/routes/EvaluationRoute.tsx` with tabbed/sectioned layout allowing evaluators to verify services, run benchmark evals, and audit rubric achievements.

### ✓ Step 4: Integrate Campaign evaluation triggers, tests, and verification
Connect live campaign transcripts to on-demand judge evaluation and verify end-to-end behavior with conservative polling.

- Add an "Evaluate with LLM Judge" button directly on `web/src/components/TranscriptView.tsx` / `web/src/routes/CampaignRoute.tsx` for completed campaigns.
- Configure conservative polling intervals (~5 minutes during in-flight runs) to prevent excessive token and API spend while campaigns execute over their 7–10 minute lifecycle.
- Add unit and component tests in `web/src/api/` and `web/src/components/` verifying health rendering, rubric score formatting, sequential pacing, and navigation flows.
- Perform end-to-end smoke verification against local mock and deployed endpoints.