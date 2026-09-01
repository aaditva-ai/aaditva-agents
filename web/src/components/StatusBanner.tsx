import type { CampaignStatus } from "../api/types";

/**
 * Renders explicit failed/stalled/starting states with a Resume action
 * where relevant (plan Functional Requirement 3, Step 6) -- a user is
 * never left watching an indefinite spinner with no explanation and no
 * escape.
 */
export function StatusBanner({
  status,
  onResume,
  isResuming,
  onEvaluate,
  isEvaluating,
  hasEvaluation,
}: {
  status: CampaignStatus;
  onResume?: () => void;
  isResuming?: boolean;
  onEvaluate?: () => void;
  isEvaluating?: boolean;
  hasEvaluation?: boolean;
}) {
  switch (status) {
    case "starting":
      return (
        <div className="text-sm bg-muted/30 px-4 py-2.5 rounded-md border border-border flex items-center justify-between gap-2">
          <span>Starting your campaign…</span>
          <span className="text-[11px] text-muted-foreground">Paced polling active (~5m lifecycles)</span>
        </div>
      );
    case "running":
      return (
        <div className="text-sm bg-muted/30 px-4 py-2.5 rounded-md border border-border flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            <span>Campaign in progress across 5 specialist agents…</span>
          </div>
          <span className="text-[11px] text-muted-foreground">Token efficient monitoring</span>
        </div>
      );
    case "complete":
      return (
        <div className="text-sm bg-emerald-50/60 dark:bg-emerald-950/30 px-4 py-2.5 rounded-md border border-emerald-500/20 text-emerald-800 dark:text-emerald-300 font-medium flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span>✓ Campaign complete. All deliverables ready.</span>
          </div>
          {onEvaluate && (
            <button
              onClick={onEvaluate}
              disabled={isEvaluating}
              className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer shadow-xs disabled:opacity-50"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="m9 11 3 3L22 4" />
                <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
              </svg>
              <span>{isEvaluating ? "Auditing..." : hasEvaluation ? "View Rubric Scorecard" : "Evaluate with LLM Judge"}</span>
            </button>
          )}
        </div>
      );
    case "failed":
      return (
        <div className="bg-destructive/10 border border-destructive/20 px-4 py-3 rounded-md flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-destructive">This campaign run failed.</span>
          <div className="flex items-center gap-2">
            {onResume && (
              <button
                onClick={onResume}
                disabled={isResuming}
                className="text-xs font-semibold text-destructive hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded px-2.5 py-1 bg-destructive/10 border border-destructive/30 cursor-pointer"
              >
                {isResuming ? "Resuming…" : "Resume"}
              </button>
            )}
            {onEvaluate && (
              <button
                onClick={onEvaluate}
                className="text-xs font-semibold px-2.5 py-1 rounded bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border cursor-pointer"
              >
                Audit Partial Run
              </button>
            )}
          </div>
        </div>
      );
    case "stalled":
      return (
        <div className="bg-yellow-50/50 dark:bg-yellow-950/30 border border-yellow-200 dark:border-yellow-900 px-4 py-2.5 rounded-md flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-yellow-800 dark:text-yellow-200">
            No progress for a while — this campaign may have stalled.
          </span>
          {onResume && (
            <button
              onClick={onResume}
              disabled={isResuming}
              className="text-xs font-semibold text-yellow-700 dark:text-yellow-300 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded px-2.5 py-1 bg-yellow-100/50 dark:bg-yellow-900/50 border border-yellow-300 dark:border-yellow-800 cursor-pointer"
            >
              {isResuming ? "Resuming…" : "Resume"}
            </button>
          )}
        </div>
      );
    default:
      return null;
  }
}
