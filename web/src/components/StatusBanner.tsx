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
      return <div className="status-banner status-banner-info">Starting your campaign…</div>;
    case "running":
      return <div className="status-banner status-banner-info">Campaign in progress…</div>;
    case "complete":
      return <div className="status-banner status-banner-success">Campaign complete.</div>;
    case "failed":
      return (
        <div className="status-banner status-banner-error">
          <span>This campaign failed.</span>
          {onResume && (
            <button onClick={onResume} disabled={isResuming}>
              {isResuming ? "Resuming…" : "Resume"}
            </button>
          )}
        </div>
      );
    case "stalled":
      return (
        <div className="status-banner status-banner-warning">
          <span>No progress for a while — this campaign may have stalled.</span>
          {onResume && (
            <button onClick={onResume} disabled={isResuming}>
              {isResuming ? "Resuming…" : "Resume"}
            </button>
          )}
        </div>
      );
    default:
      return null;
  }
}
