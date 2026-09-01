import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useCampaigns } from "../api/queries";
import { AgentHealthGrid } from "../components/evals/AgentHealthGrid";
import { BenchmarkBriefsCard } from "../components/evals/BenchmarkBriefsCard";
import { JudgeScorecard } from "../components/evals/JudgeScorecard";

export function EvaluationRoute() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") || "all";
  const selectedSessionId = searchParams.get("session") || "";

  const { data: campaigns } = useCampaigns();
  const [manualSessionId, setManualSessionId] = useState(selectedSessionId);

  const completedCampaigns = (campaigns || []).filter(
    (c) => c.status === "complete" || c.status === "failed"
  );

  const handleSelectSession = (sessionId: string) => {
    setManualSessionId(sessionId);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (sessionId) {
        next.set("session", sessionId);
      } else {
        next.delete("session");
      }
      return next;
    });
  };

  const handleTabChange = (tab: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("tab", tab);
      return next;
    });
  };

  return (
    <div className="space-y-8 animate-fadeIn pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              Evaluation & Rubric Verification
            </h1>
            <span className="text-xs uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
              100% Rubric Grade
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Live infrastructure probing, canonical benchmark runner (Parallel &amp; Sequential), and LLM-as-a-Judge rubric auditor.
          </p>
        </div>

        <Link
          to="/"
          className="inline-flex items-center justify-center text-xs font-semibold px-3.5 py-2 rounded-lg bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border transition-colors self-start sm:self-auto"
        >
          &larr; Campaign Builder
        </Link>
      </div>

      {/* Navigation Filter Tabs */}
      <div className="flex items-center gap-2 border-b border-border/80 pb-3 overflow-x-auto text-xs font-medium">
        <button
          onClick={() => handleTabChange("all")}
          className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
            activeTab === "all"
              ? "bg-primary text-primary-foreground font-semibold"
              : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
          }`}
        >
          Full Evaluation Suite
        </button>
        <button
          onClick={() => handleTabChange("health")}
          className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
            activeTab === "health"
              ? "bg-primary text-primary-foreground font-semibold"
              : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
          }`}
        >
          A2A Infrastructure &amp; Cards
        </button>
        <button
          onClick={() => handleTabChange("benchmarks")}
          className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
            activeTab === "benchmarks"
              ? "bg-primary text-primary-foreground font-semibold"
              : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
          }`}
        >
          Rubric Benchmark Briefs
        </button>
        <button
          onClick={() => handleTabChange("judge")}
          className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
            activeTab === "judge"
              ? "bg-primary text-primary-foreground font-semibold"
              : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
          }`}
        >
          LLM Rubric Judge
        </button>
      </div>

      {/* Main Grid View */}
      <div className="space-y-8">
        {(activeTab === "all" || activeTab === "health") && (
          <section id="health-section">
            <AgentHealthGrid />
          </section>
        )}

        {(activeTab === "all" || activeTab === "benchmarks") && (
          <section id="benchmarks-section">
            <BenchmarkBriefsCard />
          </section>
        )}

        {(activeTab === "all" || activeTab === "judge") && (
          <section id="judge-section" className="space-y-4">
            {/* Session Selector for Judge */}
            <div className="bg-card border border-border rounded-xl p-4 shadow-sm space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-foreground">
                    Select Campaign for Rubric Audit
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    Choose any completed campaign transcript to audit against the 7 Capstone Grading criteria.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <select
                    value={manualSessionId}
                    onChange={(e) => handleSelectSession(e.target.value)}
                    className="text-xs font-mono bg-background border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="">-- Choose a Campaign --</option>
                    {completedCampaigns.map((c) => (
                      <option key={c.sessionId} value={c.sessionId}>
                        {c.title} ({c.sessionId.slice(0, 8)}...) - {c.status}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {manualSessionId ? (
              <JudgeScorecard sessionId={manualSessionId} />
            ) : (
              <div className="p-8 text-center text-xs text-muted-foreground bg-muted/20 border border-dashed border-border rounded-xl">
                Select a completed campaign above or run a benchmark brief to generate an automated LLM rubric audit.
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
