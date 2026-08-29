import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useStartCampaign } from "../api/queries";
import { useAuth } from "../auth/AuthProvider";
import { RecentCampaigns } from "../components/RecentCampaigns";

export function HomeRoute() {
  const [prompt, setPrompt] = useState("");
  const navigate = useNavigate();
  const { signOutUser, user } = useAuth();
  const startCampaign = useStartCampaign();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || startCampaign.isPending) return;
    startCampaign.mutate(prompt, {
      onSuccess: ({ sessionId }) => {
        // The route param is the durable handle (plan Step 4) -- no
        // localStorage write, the URL itself is what makes this campaign
        // reachable again after a reload or a shared link.
        navigate(`/c/${sessionId}`);
      },
    });
  };

  return (
    <div className="home-page">
      <header className="home-header">
        <h1>Aaditva Campaign Builder</h1>
        <div>
          <span>{user?.displayName ?? user?.email}</span>
          <button onClick={() => void signOutUser()}>Sign out</button>
        </div>
      </header>

      <form onSubmit={handleSubmit} className="brief-form">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe the Instagram campaign you want..."
          rows={6}
          disabled={startCampaign.isPending}
        />
        {/* isPending disables the button, which also prevents duplicate
            campaign starts from a double-click (plan Step 4). */}
        <button type="submit" disabled={startCampaign.isPending || !prompt.trim()}>
          {startCampaign.isPending ? "Starting…" : "Start campaign"}
        </button>
        {startCampaign.isError && (
          <p className="error-text">{startCampaign.error.message}</p>
        )}
      </form>

      <RecentCampaigns />
    </div>
  );
}
