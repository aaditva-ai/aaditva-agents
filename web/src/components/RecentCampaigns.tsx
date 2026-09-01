import { Link } from "react-router-dom";
import { useCampaigns } from "../api/queries";

/**
 * The server-side replacement for localStorage (plan Functional
 * Requirement 4a / Step 6): any campaign is reachable here regardless of
 * device or cleared browser storage, since it comes from GET /campaigns
 * rather than anything held client-side.
 */
export function RecentCampaigns() {
  const { data: campaigns, isLoading, isError } = useCampaigns();

  if (isLoading) return (
    <p className="text-center text-sm text-muted-foreground py-8">
      Loading recent campaigns…<br />
      <span className="mt-2 inline-block w-full max-w-xs h-3 bg-muted rounded animate-pulse" />
    </p>
  );
  if (isError) return <p className="text-center text-sm text-destructive bg-destructive/10 px-4 py-3 rounded-md">Could not load recent campaigns.</p>;
  if (!campaigns || campaigns.length === 0) return (
    <section className="flex flex-col items-center justify-center py-8 gap-2 text-muted-foreground">
      <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 10h6M9 14h6m-9-8v14m9-14v14M2 10h20a2 2 0 0 1 2 2v1a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-1a2 2 0 0 1 2-2z"/></svg>
      <p className="text-center text-sm">No recent campaigns yet</p>
    </section>
  );

  return (
    <section className="space-y-3 mb-8">
      <h2 className="text-lg font-semibold tracking-tight">Recent campaigns</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {campaigns.map((c) => (
          <Link
            key={c.sessionId}
            to={`/c/${c.sessionId}`}
            className="flex items-center gap-3 px-4 py-3 rounded-lg border border-border bg-card hover:bg-accent transition-colors group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Open campaign: ${c.title || "(untitled campaign)"} (${c.status})`}
          >
            <span
              className={`w-2 h-2 rounded-full flex-shrink-0 ${
                c.status === 'complete' ? 'bg-emerald-500' :
                c.status === 'running' ? 'bg-blue-500' :
                c.status === 'failed' ? 'bg-red-500' : 'bg-yellow-500'
              }`}
              aria-hidden="true"
            />
            <span className="flex-1 text-sm font-medium tracking-tight">
              {c.title || '(untitled campaign)'}
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
