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

  if (isLoading) return <p>Loading recent campaigns…</p>;
  if (isError) return <p className="error-text">Could not load recent campaigns.</p>;
  if (!campaigns || campaigns.length === 0) return null;

  return (
    <section className="recent-campaigns">
      <h2>Recent campaigns</h2>
      <ul>
        {campaigns.map((c) => (
          <li key={c.sessionId}>
            <Link to={`/c/${c.sessionId}`}>
              <span className={`status-dot status-${c.status}`} />
              {c.title || "(untitled campaign)"}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
