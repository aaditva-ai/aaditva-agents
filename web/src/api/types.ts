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
  status: CampaignDocStatus;
  createdAt: string | null;
  lastEventAt: string | null;
}

export interface EventsPage {
  cursor: string | null;
  status: CampaignStatus;
  steps: Step[];
}
