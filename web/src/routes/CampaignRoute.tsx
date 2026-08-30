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
    <div className="flex flex-col bg-background min-h-screen">
      <header className="flex items-center gap-3 p-4 border-b border-border bg-card shadow-sm sticky top-0 z-10">
        <Link to="/" className="text-primary hover:underline text-sm font-medium">← All campaigns</Link>
      </header>

      {/* isError + failureCount surfaces a non-blocking "reconnecting"
          indicator during backoff while already-fetched pages keep
          rendering underneath -- a transient broker 5xx or network loss
          never wipes the transcript (plan Step 6 / Functional Requirement
          8), unlike gradio-ui/app.py's single-error-bubble replacement. */}
      {query.isError && (
        <div className="text-center text-sm text-muted-foreground bg-yellow-50 py-3 px-4 rounded-md">
          Reconnecting… (attempt {query.failureCount})
        </div>
      )}

      {/* Empty state for new campaigns */}
      {!query.data && !query.isLoading && query.isSuccess && (
        <section className="flex flex-col items-center justify-center py-12 gap-4 text-muted-foreground bg-muted/30 rounded-lg border border-border">
          <svg className="w-16 h-16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
          <p className="text-center text-sm">Campaign started - transcript loading</p>
        </section>
      )}

      {query.data && query.data.length > 0 ? (
        <TranscriptView
          transcript={query.data}
          onResume={RESUMABLE_STATUSES.has(query.data.status) ? () => resume.mutate() : undefined}
          isResuming={resume.isPending}
        />
      ) : query.isLoading ? (
        <div className="flex flex-col items-center justify-center py-12 gap-3">
          <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground">Loading campaign…</p>
        </div>
      ) : null}

      {resume.isError && (
        <p className="text-center text-sm text-destructive bg-destructive/10 px-4 py-2 rounded-md">{resume.error.message}</p>
      )}
    </div>
  );
}
