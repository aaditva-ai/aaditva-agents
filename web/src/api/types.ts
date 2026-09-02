// Mirrors broker/main.py's response shapes and events_normalizer.py's step
// shape exactly (see docs/replace-gradio-with-spa-job-architecture.md's
// Data Models / Contracts section) -- kept as one file so a broker
// response-shape change is a one-place update on the client.

// GET /campaigns returns the raw Firestore campaign-document status.
export type CampaignDocStatus = "dispatched" | "running" | "complete" | "failed";

// GET /campaigns/{id}/events returns the *derived* status (broker/main.py's
// _derive_status), which folds event-staleness into the doc status --
// "dispatched" becomes "starting", and either non-terminal status can
// become "stalled" if nothing new has landed recently.
export type CampaignStatus = "starting" | "running" | "complete" | "failed" | "stalled";

export type StepKind = "text" | "tool_call" | "tool_result" | "image" | "transfer";

export interface Step {
  id: string;
  author: string | null;
  invocationId: string | null;
  kind: StepKind;
  text?: string;
  toolName?: string;
  imageUrl?: string;
  timestamp: string | null;
}

export interface CampaignSummary {
  sessionId: string;
  title: string;
  prompt?: string;
  status: CampaignDocStatus;
  createdAt: string | null;
  lastEventAt: string | null;
}

export interface EventsPage {
  cursor: string | null;
  status: CampaignStatus;
  steps: Step[];
}

export interface ServiceHealthItem {
  id: string;
  name: string;
  description: string;
  url: string;
  status: "online" | "degraded" | "offline";
  statusCode: number | null;
  latencyMs: number;
  card?: Record<string, any> | null;
  error?: string | null;
}

export interface AgentHealthReport {
  timestamp: string;
  allHealthy: boolean;
  services: ServiceHealthItem[];
}

export interface BenchmarkBrief {
  id: string;
  title: string;
  prompt: string;
  category: string;
  focus: string;
  targetRubricCriterion: string;
  expectedRounds: number;
  cooldownSeconds: number;
}

export interface CriterionEval {
  id: number;
  name: string;
  weight: number;
  score: number;
  rating: "Excellent" | "Good" | "Developing" | "Unsatisfactory";
  passed: boolean;
  rationale: string;
  evidence: string[];
}

export interface JudgeEvaluationResult {
  sessionId: string;
  evaluatedAt: string;
  prompt?: string;
  overallScore: number;
  overallGrade: "Excellent" | "Good" | "Developing" | "Unsatisfactory";
  summary: string;
  criteria: CriterionEval[];
  evaluated?: boolean;
}

export interface QuotaStatusResponse {
  status: "ready" | "pending" | "error";
  elevated: boolean;
  model: string;
  targetRpm: number;
  regions: string[];
  queueName?: string;
  projectId?: string;
  timestamp?: string;
  message: string;
}
