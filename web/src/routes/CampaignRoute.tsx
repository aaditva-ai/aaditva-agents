import { useParams, Link } from "react-router-dom";
import { useCampaignEvents, useResumeCampaign } from "../api/queries";
import { TranscriptView } from "../components/TranscriptView";

const RESUMABLE_STATUSES = new Set(["failed", "stalled"]);

/**
 * The route param is the durable handle (plan Step 4/5): a reload, a
 * shared link, or opening this from a different device all resolve here
 * the same way -- useCampaignEvents refetches from the server with no
 * client-held execution handle beyond this sessionId.
 */
export function CampaignRoute() {
  const { sessionId } = useParams<{ sessionId: string }>();
  if (!sessionId) return null;

  const query = useCampaignEvents(sessionId);
  const resume = useResumeCampaign(sessionId);

  return (
    <div className="campaign-page">
      <header className="campaign-header">
        <Link to="/">&larr; All campaigns</Link>
      </header>

      {/* isError + failureCount surfaces a non-blocking "reconnecting"
          indicator during backoff while already-fetched pages keep
          rendering underneath -- a transient broker 5xx or network loss
          never wipes the transcript (plan Step 6 / Functional Requirement
          8), unlike gradio-ui/app.py's single-error-bubble replacement. */}
      {query.isError && (
        <div className="status-banner status-banner-warning">
          Reconnecting… (attempt {query.failureCount})
        </div>
      )}

      {query.data ? (
        <TranscriptView
          transcript={query.data}
          onResume={RESUMABLE_STATUSES.has(query.data.status) ? () => resume.mutate() : undefined}
          isResuming={resume.isPending}
        />
      ) : query.isLoading ? (
        <p>Loading campaign…</p>
      ) : null}

      {resume.isError && <p className="error-text">{resume.error.message}</p>}
    </div>
  );
}
