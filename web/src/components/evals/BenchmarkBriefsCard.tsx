import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import {
  useBenchmarkBriefs,
  useStartCampaign,
  useCampaigns,
  useCampaignEvaluation,
  useTriggerJudgeEval,
} from "../../api/queries";
import type { BenchmarkBrief, CampaignSummary } from "../../api/types";

interface BatchRunState {
  briefId: string;
  status: "idle" | "launching" | "dispatched" | "running" | "complete" | "error";
  sessionId?: string;
  error?: string;
}

const STORAGE_KEY = "eval_benchmark_batch_states";

function loadPersistedStates(): Record<string, BatchRunState> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function savePersistedStates(states: Record<string, BatchRunState>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(states));
  } catch (err) {
    console.error("Failed to save benchmark states to localStorage:", err);
  }
}

interface BenchmarkBriefItemProps {
  brief: BenchmarkBrief;
  idx: number;
  batchState?: BatchRunState;
  matchingCampaign?: CampaignSummary;
  isPendingLaunch: boolean;
  isAnyCampaignRunning: boolean;
  onLaunch: (brief: BenchmarkBrief) => Promise<void>;
}

function BenchmarkBriefItem({
  brief,
  idx,
  batchState,
  matchingCampaign,
  isPendingLaunch,
  isAnyCampaignRunning,
  onLaunch,
}: BenchmarkBriefItemProps) {
  const activeSessionId = batchState?.sessionId || matchingCampaign?.sessionId;
  const { data: evaluation } = useCampaignEvaluation(activeSessionId);
  const triggerJudge = useTriggerJudgeEval();

  const hasEvaluation = Boolean(
    evaluation && evaluation.evaluated !== false && typeof evaluation.overallScore === "number"
  );

  let derivedStatus: "launching" | "running" | "complete" | "failed" | "idle" = "idle";
  if (batchState?.status === "launching") {
    derivedStatus = "launching";
  } else if (
    matchingCampaign?.status === "running" ||
    matchingCampaign?.status === "dispatched" ||
    (batchState?.status === "running" &&
      matchingCampaign?.status !== "complete" &&
      matchingCampaign?.status !== "failed") ||
    (batchState?.status === "dispatched" &&
      matchingCampaign?.status !== "complete" &&
      matchingCampaign?.status !== "failed")
  ) {
    derivedStatus = "running";
  } else if (
    matchingCampaign?.status === "complete" ||
    (batchState?.status === "complete" && matchingCampaign?.status !== "failed")
  ) {
    derivedStatus = "complete";
  } else if (
    matchingCampaign?.status === "failed" ||
    (batchState?.status === "error" && matchingCampaign?.status !== "complete")
  ) {
    derivedStatus = "failed";
  }

  const isLaunching = derivedStatus === "launching";
  const isRunning = derivedStatus === "running";
  const isCompleted = derivedStatus === "complete";
  const isFailed = derivedStatus === "failed";

  const hasPreviousRun = Boolean(activeSessionId);
  const isButtonDisabled = isPendingLaunch || isAnyCampaignRunning;
  const isEvaluating = triggerJudge.isPending;

  // Auto-trigger evaluation when benchmark campaign completes if no evaluation exists yet
  const autoTriggeredSessions = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (
      isCompleted &&
      activeSessionId &&
      evaluation !== undefined &&
      evaluation.evaluated === false &&
      !isEvaluating &&
      !autoTriggeredSessions.current.has(activeSessionId)
    ) {
      autoTriggeredSessions.current.add(activeSessionId);
      triggerJudge.mutate({ sessionId: activeSessionId, force: false });
    }
  }, [isCompleted, activeSessionId, evaluation, isEvaluating, triggerJudge]);

  const handleEvaluate = async () => {
    if (!activeSessionId || isEvaluating) return;
    try {
      await triggerJudge.mutateAsync({ sessionId: activeSessionId, force: false });
    } catch (err) {
      console.error("Evaluation trigger failed:", err);
    }
  };

  const getGradeBadgeColor = (grade?: string) => {
    switch (grade) {
      case "Excellent":
        return "bg-emerald-500/10 text-emerald-500 border-emerald-500/30";
      case "Good":
        return "bg-blue-500/10 text-blue-500 border-blue-500/30";
      case "Developing":
        return "bg-amber-500/10 text-amber-500 border-amber-500/30";
      default:
        return "bg-rose-500/10 text-rose-500 border-rose-500/30";
    }
  };

  return (
    <div className="p-4 rounded-xl border border-border/80 bg-background/60 hover:bg-muted/30 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div className="space-y-2 min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-mono font-bold text-muted-foreground px-1.5 py-0.5 rounded bg-muted">
            #{idx + 1}
          </span>
          <span className="font-semibold text-sm text-foreground">{brief.title}</span>
          <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground border border-border">
            {brief.category}
          </span>

          {/* Status and Previous Run Indicators */}
          {isLaunching && (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-500 border border-amber-500/20">
              <svg className="w-2.5 h-2.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="12" />
              </svg>
              Launching...
            </span>
          )}

          {isRunning && !isLaunching && (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-500 border border-blue-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
              Live Run in Progress
            </span>
          )}

          {isCompleted && (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
              ✓ Run Completed
            </span>
          )}

          {isFailed && (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20">
              ⚠ Run Failed
            </span>
          )}
        </div>

        <p className="text-xs text-foreground/80 font-mono bg-muted/30 p-2 rounded-md border border-border/40">
          &ldquo;{brief.prompt}&rdquo;
        </p>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground pt-0.5">
          <span className="flex items-center gap-1">
            <strong className="text-foreground/90">Exercises:</strong> {brief.focus}
          </span>
          <span className="text-primary font-medium">
            🎯 {brief.targetRubricCriterion}
          </span>
        </div>

        {/* Previous Evaluation Card Banner */}
        {hasEvaluation && evaluation && (
          <div className="mt-2 p-2.5 rounded-lg bg-card/80 border border-border/70 flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground font-medium">Last Evaluation:</span>
              <span
                className={`px-2 py-0.5 rounded-md font-bold text-[11px] border ${getGradeBadgeColor(
                  evaluation.overallGrade
                )}`}
              >
                {evaluation.overallGrade} ({evaluation.overallScore.toFixed(1)}%)
              </span>
              <span className="text-muted-foreground text-[11px] line-clamp-1 max-w-md hidden sm:inline">
                {evaluation.summary}
              </span>
            </div>

            <Link
              to={`/evaluation?tab=judge&session=${activeSessionId}`}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
            >
              <span>View Rubric Audit</span>
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14" />
                <path d="m12 5 7 7-7 7" />
              </svg>
            </Link>
          </div>
        )}
      </div>

      <div className="flex flex-col sm:flex-row md:flex-col lg:flex-row items-stretch sm:items-center gap-2 shrink-0 self-start md:self-center">
        {activeSessionId && (
          <a
            href={`/c/${activeSessionId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-1 text-xs font-medium px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 border border-emerald-500/30 transition-colors cursor-pointer"
            title="Opens live campaign run transcript in a new tab"
          >
            <span>View Live Run</span>
            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </a>
        )}

        {isCompleted && !hasEvaluation && activeSessionId && (
          <button
            onClick={() => void handleEvaluate()}
            disabled={isEvaluating}
            className="inline-flex items-center justify-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 border border-primary/30 transition-colors cursor-pointer disabled:opacity-50"
            title="Evaluate this completed campaign against the rubric"
          >
            <svg
              className={`w-3 h-3 ${isEvaluating ? "animate-spin" : ""}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
              <path d="M16 21h5v-5" />
            </svg>
            <span>{isEvaluating ? "Auditing Rubric..." : "Evaluate Rubric"}</span>
          </button>
        )}

        <div
          className="inline-flex"
          title={
            isAnyCampaignRunning
              ? "Cannot launch while a campaign run is currently in progress. Please wait for it to complete."
              : undefined
          }
        >
          <button
            onClick={() => void onLaunch(brief)}
            disabled={isButtonDisabled}
            title={
              isAnyCampaignRunning
                ? "Cannot launch while a campaign run is currently in progress. Please wait for it to complete."
                : undefined
            }
            className={`inline-flex items-center justify-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg border transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
              hasPreviousRun
                ? "bg-secondary text-secondary-foreground hover:bg-secondary/80 border-border"
                : "bg-primary text-primary-foreground hover:bg-primary/90 border-transparent shadow-xs"
            }`}
          >
            {hasPreviousRun ? (
              <>
                <svg className="w-3 h-3 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                  <path d="M3 3v5h5" />
                  <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                  <path d="M16 21h5v-5" />
                </svg>
                <span>Re-run Brief</span>
              </>
            ) : (
              <>
                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
                <span>Launch This Brief</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export function BenchmarkBriefsCard() {
  const { data: benchmarks, isLoading, error } = useBenchmarkBriefs();
  const { data: campaigns } = useCampaigns();
  const startCampaign = useStartCampaign();

  const [batchStates, setBatchStates] = useState<Record<string, BatchRunState>>(() => loadPersistedStates());

  const updateBatchStates = (updater: (prev: Record<string, BatchRunState>) => Record<string, BatchRunState>) => {
    setBatchStates((prev) => {
      const next = updater(prev);
      savePersistedStates(next);
      return next;
    });
  };

  const findMatchingCampaign = (brief: BenchmarkBrief): CampaignSummary | undefined => {
    if (!campaigns || campaigns.length === 0) return undefined;
    const batchSessionId = batchStates[brief.id]?.sessionId;
    if (batchSessionId) {
      const found = campaigns.find((c) => c.sessionId === batchSessionId);
      if (found) return found;
    }
    // Match by prompt
    return campaigns.find((c) => (c.prompt || c.title || "").trim() === brief.prompt.trim());
  };

  const isAnyCampaignRunning = Boolean(
    startCampaign.isPending ||
    campaigns?.some((c) => c.status === "running" || c.status === "dispatched") ||
    benchmarks?.some((b) => {
      const state = batchStates[b.id];
      if (!state) return false;
      if (state.status === "launching") return true;
      const matched = findMatchingCampaign(b);
      if (matched) {
        return matched.status === "running" || matched.status === "dispatched";
      }
      return state.status === "dispatched" || state.status === "running";
    })
  );

  const launchSingleBrief = async (brief: BenchmarkBrief) => {
    if (isAnyCampaignRunning) return;

    updateBatchStates((prev) => ({
      ...prev,
      [brief.id]: { briefId: brief.id, status: "launching" },
    }));

    try {
      const res = await startCampaign.mutateAsync(brief.prompt);
      updateBatchStates((prev) => ({
        ...prev,
        [brief.id]: {
          briefId: brief.id,
          status: "dispatched",
          sessionId: res.sessionId,
        },
      }));
      // Open the live run in a new tab without navigating away from the evaluation dashboard
      window.open(`/c/${res.sessionId}`, "_blank");
    } catch (err) {
      updateBatchStates((prev) => ({
        ...prev,
        [brief.id]: {
          briefId: brief.id,
          status: "error",
          error: (err as Error).message || "Failed to launch",
        },
      }));
    }
  };

  const handleClearHistory = () => {
    setBatchStates({});
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl p-5 space-y-4 shadow-sm">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-border/70">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-foreground tracking-tight">
              Curated Rubric Benchmark Briefs
            </h2>
            <span className="text-xs px-2 py-0.5 rounded-full font-semibold bg-primary/10 text-primary border border-primary/20">
              5 Canonical Tests
            </span>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            Pre-configured briefs specifically curated in EVALUATION.md to verify every rubric criterion.
          </p>
        </div>

        {isAnyCampaignRunning && (
          <div className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg bg-blue-500/10 text-blue-500 border border-blue-500/20 font-medium shrink-0">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
            <span>Campaign in progress — other launches disabled</span>
          </div>
        )}
      </div>

      {error && (
        <div className="p-3 bg-destructive/10 border border-destructive/20 text-destructive text-xs rounded-lg">
          Failed to load benchmark briefs: {(error as Error).message}
        </div>
      )}

      {isLoading && !benchmarks ? (
        <div className="space-y-3 pt-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-20 rounded-lg bg-muted/40 animate-pulse border border-border/50" />
          ))}
        </div>
      ) : (
        <div className="space-y-3 pt-1">
          {benchmarks?.map((brief, idx) => {
            const batchState = batchStates[brief.id];
            const matchingCampaign = findMatchingCampaign(brief);
            return (
              <BenchmarkBriefItem
                key={brief.id}
                brief={brief}
                idx={idx}
                batchState={batchState}
                matchingCampaign={matchingCampaign}
                isPendingLaunch={startCampaign.isPending}
                isAnyCampaignRunning={isAnyCampaignRunning}
                onLaunch={launchSingleBrief}
              />
            );
          })}
        </div>
      )}

      <div className="text-[11px] text-muted-foreground flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-2 border-t border-border/60">
        <span>Runs execute across 5 specialist agents with Cloud Tasks backoff retry protection.</span>
        {Object.keys(batchStates).length > 0 && (
          <button
            onClick={handleClearHistory}
            className="text-muted-foreground hover:text-foreground underline cursor-pointer"
          >
            Clear Run Tracking History
          </button>
        )}
      </div>
    </div>
  );
}
