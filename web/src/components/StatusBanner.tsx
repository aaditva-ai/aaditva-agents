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
}: {
  status: CampaignStatus;
  onResume?: () => void;
  isResuming?: boolean;
}) {
  switch (status) {
    case "starting":
      return <div className="text-sm bg-muted/30 px-4 py-2.5 rounded-md border border-border">Starting your campaign…</div>;
    case "running":
      return <div className="text-sm bg-muted/30 px-4 py-2.5 rounded-md border border-border">Campaign in progress…</div>;
    case "complete":
      return <div className="text-sm bg-emerald-50/50 px-4 py-2.5 rounded-md border border-border text-emerald-800 font-medium">✓ Campaign complete.</div>;
    case "failed":
      return (
        <div className="bg-destructive/10 border border-destructive/20 px-4 py-3 rounded-md">
          <span className="text-sm">This campaign failed.</span>
          {onResume && (
            <button
              onClick={onResume}
              disabled={isResuming}
              className="ml-3 text-sm font-medium text-destructive hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded px-2 py-1"
            >
              {isResuming ? "Resuming…" : "Resume"}
            </button>
          )}
        </div>
      );
    case "stalled":
      return (
        <div className="bg-yellow-50/50 border border-yellow-200 px-4 py-2.5 rounded-md">
          <span className="text-sm text-yellow-800">No progress for a while — this campaign may have stalled.</span>
          {onResume && (
            <button
              onClick={onResume}
              disabled={isResuming}
              className="ml-3 text-sm font-medium text-yellow-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded px-2 py-1"
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
