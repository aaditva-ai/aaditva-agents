import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useStartCampaign } from "../api/queries";
import { RecentCampaigns } from "../components/RecentCampaigns";

export function HomeRoute() {
  const [prompt, setPrompt] = useState("");
  const navigate = useNavigate();
  const startCampaign = useStartCampaign();

  const error = startCampaign.isError && startCampaign.error ? startCampaign.error.message : null;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || startCampaign.isPending) return;
    startCampaign.mutate(prompt, {
      onSuccess: ({ sessionId }) => navigate(`/c/${sessionId}`),
    });
  };

  return (
    <div className="flex flex-col w-full max-w-2xl mx-auto py-2">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight mb-1 text-foreground">Create a Campaign</h1>
        <p className="text-sm text-muted-foreground">
          Describe the marketing campaign you want to build and let AI orchestrate the assets.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4 mb-8 bg-card border border-border p-5 rounded-xl shadow-sm">
        <label htmlFor="campaign-prompt" className="text-sm font-semibold text-foreground">
          Prompt
        </label>
        <textarea
          id="campaign-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe the Instagram campaign you want (e.g., 'Create a 3-step demo explaining AI for beginners')..."
          rows={4}
          disabled={startCampaign.isPending}
          className="w-full px-4 py-3 text-sm bg-background border border-input rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 transition-all"
        />
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={startCampaign.isPending || !prompt.trim()}
            className="w-full sm:w-auto px-6 py-2.5 text-sm font-semibold bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all rounded-lg shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
          >
            {startCampaign.isPending ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Starting…
              </span>
            ) : (
              "Start campaign"
            )}
          </button>
        </div>
        {error && (
          <p className="text-sm text-destructive bg-destructive/10 border border-destructive/20 px-3 py-2 rounded-md">
            {error}
          </p>
        )}
      </form>

      <RecentCampaigns />
    </div>
  );
}
