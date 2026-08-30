import { useState, useEffect, type FormEvent } from "react";
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
      onSuccess: ({ sessionId }) => navigate(`/c/${sessionId}`),
    });
  };

  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (startCampaign.isError) setError(startCampaign.error.message);
    else setError(null);
  }, [startCampaign.isError]);

  return (
    <div className="flex flex-col min-h-screen bg-background text-foreground px-4 py-8 max-w-md mx-auto">
      <header className="flex items-center justify-between mb-8 gap-4 p-4 rounded-lg border border-border bg-card shadow-sm">
        <h1 className="text-2xl font-semibold tracking-tight">Aaditva Campaign Builder</h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">{user?.displayName ?? user?.email}</span>
          <button
            onClick={() => void signOutUser()}
            className="px-3 py-1.5 text-sm font-medium text-destructive bg-destructive hover:bg-destructive/90 rounded-md border border-destructive/20 transition-colors"
          >Sign out</button>
        </div>
      </header>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4 mb-8">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe the Instagram campaign you want (e.g., 'Create a 3-step demo explaining AI for beginners')..."
          rows={5}
          disabled={startCampaign.isPending}
          className="flex-1 w-full px-4 py-3 text-base bg-background border border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 transition-all font-medium"
        />
        <button
          type="submit"
          disabled={startCampaign.isPending || !prompt.trim()}
          className="w-full px-4 py-3 text-base font-semibold bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all rounded-lg shadow-sm border border-border"
        >
          {startCampaign.isPending ? <span className="flex items-center justify-center gap-2"><svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></span> : "Start campaign"}
        </button>
        {error && <p className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded-md">{error}</p>}
      </form>

      <section className="flex flex-col gap-2 mb-4">
        <h2 className="text-lg font-semibold tracking-tight">Recent campaigns</h2>
      </section>
      <RecentCampaigns />
    </div>
  );
}
