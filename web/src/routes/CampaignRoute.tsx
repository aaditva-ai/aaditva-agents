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

  const query = useCampaignEvents(sessionId);
  const resume = useResumeCampaign(sessionId);

  if (!sessionId) return null;

  return (
    <div className="flex flex-col w-full">
      <div className="mb-6 flex items-center justify-between">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md px-1 py-0.5"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m15 18-6-6 6-6" />
          </svg>
          Back to all campaigns
        </Link>
        <span className="text-xs font-mono text-muted-foreground bg-muted px-2 py-1 rounded border border-border">
          Session: {sessionId.slice(0, 8)}…
        </span>
      </div>

      {/* isError + failureCount surfaces a non-blocking "reconnecting"
          indicator during backoff while already-fetched pages keep
          rendering underneath -- a transient broker 5xx or network loss
          never wipes the transcript (plan Step 6 / Functional Requirement
          8), unlike gradio-ui/app.py's single-error-bubble replacement. */}
      {query.isError && (
        <div className="text-center text-sm text-yellow-800 dark:text-yellow-200 bg-yellow-50 dark:bg-yellow-950/30 border border-yellow-200 dark:border-yellow-900 py-3 px-4 rounded-lg mb-4">
          Reconnecting… (attempt {query.failureCount})
        </div>
      )}

      {/* Empty state for new campaigns */}
      {!query.data && !query.isLoading && query.isSuccess && (
        <section className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground bg-muted/20 rounded-xl border border-border">
          <svg className="w-12 h-12 text-muted-foreground/60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 6v6l4 2" />
          </svg>
          <p className="text-center text-sm font-medium">Campaign started — waiting for first event…</p>
        </section>
      )}

      {query.data && query.data.groups.length > 0 ? (
        <TranscriptView
          transcript={query.data}
          onResume={RESUMABLE_STATUSES.has(query.data.status) ? () => resume.mutate() : undefined}
          isResuming={resume.isPending}
        />
      ) : query.isLoading ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground font-medium">Loading campaign…</p>
        </div>
      ) : null}

      {resume.isError && (
        <p className="mt-4 text-center text-sm text-destructive bg-destructive/10 border border-destructive/20 px-4 py-2 rounded-lg">
          {resume.error.message}
        </p>
      )}
    </div>
  );
}
