import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useBenchmarkBriefs, useStartCampaign } from "../../api/queries";
import type { BenchmarkBrief } from "../../api/types";

interface BatchRunState {
  briefId: string;
  status: "idle" | "launching" | "dispatched" | "running" | "complete" | "error";
  sessionId?: string;
  error?: string;
}

export function BenchmarkBriefsCard() {
  const navigate = useNavigate();
  const { data: benchmarks, isLoading, error } = useBenchmarkBriefs();
  const startCampaign = useStartCampaign();

  const [execMode, setExecMode] = useState<"parallel" | "sequential">("parallel");
  const [batchStates, setBatchStates] = useState<Record<string, BatchRunState>>({});
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  const [batchProgressMsg, setBatchProgressMsg] = useState<string | null>(null);

  const launchSingleBrief = async (brief: BenchmarkBrief) => {
    try {
      const res = await startCampaign.mutateAsync(brief.prompt);
      navigate(`/c/${res.sessionId}`);
    } catch (err) {
      console.error("Failed to launch brief campaign:", err);
    }
  };

  const runAllBenchmarks = async () => {
    if (!benchmarks || benchmarks.length === 0 || isBatchRunning) return;

    setIsBatchRunning(true);
    const initialStates: Record<string, BatchRunState> = {};
    for (const b of benchmarks) {
      initialStates[b.id] = { briefId: b.id, status: "idle" };
    }
    setBatchStates(initialStates);

    if (execMode === "parallel") {
      setBatchProgressMsg("Dispatching all 5 benchmarks in Parallel Mode (Vertex AI Quota scaled)...");
      await Promise.all(
        benchmarks.map(async (brief) => {
          setBatchStates((prev) => ({
            ...prev,
            [brief.id]: { briefId: brief.id, status: "launching" },
          }));
          try {
            const res = await startCampaign.mutateAsync(brief.prompt);
            setBatchStates((prev) => ({
              ...prev,
              [brief.id]: {
                briefId: brief.id,
                status: "dispatched",
                sessionId: res.sessionId,
              },
            }));
          } catch (err) {
            setBatchStates((prev) => ({
              ...prev,
              [brief.id]: {
                briefId: brief.id,
                status: "error",
                error: (err as Error).message || "Failed to launch",
              },
            }));
          }
        })
      );
      setBatchProgressMsg("All 5 benchmarks dispatched concurrently! Monitoring via Cloud Tasks backoff.");
      setIsBatchRunning(false);
    } else {
      // Sequential execution with cooldown buffer
      for (let i = 0; i < benchmarks.length; i++) {
        const brief = benchmarks[i];
        setBatchProgressMsg(
          `Launching benchmark [${i + 1}/${benchmarks.length}]: ${brief.title}...`
        );
        setBatchStates((prev) => ({
          ...prev,
          [brief.id]: { briefId: brief.id, status: "launching" },
        }));

        try {
          const res = await startCampaign.mutateAsync(brief.prompt);
          setBatchStates((prev) => ({
            ...prev,
            [brief.id]: {
              briefId: brief.id,
              status: "dispatched",
              sessionId: res.sessionId,
            },
          }));
        } catch (err) {
          setBatchStates((prev) => ({
            ...prev,
            [brief.id]: {
              briefId: brief.id,
              status: "error",
              error: (err as Error).message || "Failed",
            },
          }));
        }

        if (i < benchmarks.length - 1) {
          const cooldown = brief.cooldownSeconds || 15;
          setBatchProgressMsg(`Pacing cooldown (${cooldown}s) before next run to protect image quotas...`);
          await new Promise((r) => setTimeout(r, cooldown * 1000));
        }
      }
      setBatchProgressMsg("Sequential benchmark dispatch completed!");
      setIsBatchRunning(false);
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl p-5 space-y-4 shadow-sm">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-border/70">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-foreground tracking-tight">
              Curated Rubric Benchmark Briefs
            </h2>
            <span className="text-xs px-2 py-0.5 rounded-full font-semibold bg-primary/10 text-primary border border-primary/20">
              5 Canonical Tests
            </span>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            Pre-configured briefs specifically curated in EVALUATION.md to verify every rubric criterion.
          </p>
        </div>

        {/* Execution Mode Controls & Run All Action */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center bg-muted/70 p-1 rounded-lg border border-border text-xs font-medium">
            <button
              onClick={() => setExecMode("parallel")}
              className={`px-2.5 py-1 rounded-md transition-all cursor-pointer ${
                execMode === "parallel"
                  ? "bg-primary text-primary-foreground font-semibold shadow-xs"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Parallel Mode
            </button>
            <button
              onClick={() => setExecMode("sequential")}
              className={`px-2.5 py-1 rounded-md transition-all cursor-pointer ${
                execMode === "sequential"
                  ? "bg-primary text-primary-foreground font-semibold shadow-xs"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Sequential Mode
            </button>
          </div>

          <button
            onClick={() => void runAllBenchmarks()}
            disabled={isBatchRunning || !benchmarks || benchmarks.length === 0}
            className="inline-flex items-center justify-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors cursor-pointer shadow-sm"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
            <span>{isBatchRunning ? "Running Suite..." : "Run All Benchmarks"}</span>
          </button>
        </div>
      </div>

      {batchProgressMsg && (
        <div className="p-3 bg-primary/10 border border-primary/20 text-foreground text-xs rounded-lg flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            <span className="font-medium">{batchProgressMsg}</span>
          </div>
          <span className="text-[11px] text-muted-foreground font-mono">
            {execMode === "parallel" ? "Parallel Quota Scaled" : "Paced Cooldown"}
          </span>
        </div>
      )}

      {error && (
        <div className="p-3 bg-destructive/10 border border-destructive/20 text-destructive text-xs rounded-lg">
          Failed to load benchmark briefs: {(error as Error).message}
        </div>
      )}

      {isLoading && !benchmarks ? (
        <div className="space-y-3 pt-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-20 rounded-lg bg-muted/40 animate-pulse border border-border/50" />
          ))}
        </div>
      ) : (
        <div className="space-y-3 pt-1">
          {benchmarks?.map((brief, idx) => {
            const batchState = batchStates[brief.id];
            return (
              <div
                key={brief.id}
                className="p-4 rounded-xl border border-border/80 bg-background/60 hover:bg-muted/30 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4"
              >
                <div className="space-y-1.5 min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-mono font-bold text-muted-foreground px-1.5 py-0.5 rounded bg-muted">
                      #{idx + 1}
                    </span>
                    <span className="font-semibold text-sm text-foreground">{brief.title}</span>
                    <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground border border-border">
                      {brief.category}
                    </span>
                  </div>

                  <p className="text-xs text-foreground/80 font-mono bg-muted/30 p-2 rounded-md border border-border/40">
                    &ldquo;{brief.prompt}&rdquo;
                  </p>

                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground pt-0.5">
                    <span className="flex items-center gap-1">
                      <strong className="text-foreground/90">Exercises:</strong> {brief.focus}
                    </span>
                    <span className="text-primary font-medium">
                      🎯 {brief.targetRubricCriterion}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2.5 shrink-0 self-start md:self-center">
                  {batchState?.sessionId ? (
                    <button
                      onClick={() => navigate(`/c/${batchState.sessionId}`)}
                      className="inline-flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 border border-emerald-500/30 transition-colors cursor-pointer"
                    >
                      <span>View Live Run</span>
                      <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                        <polyline points="15 3 21 3 21 9" />
                        <line x1="10" y1="14" x2="21" y2="3" />
                      </svg>
                    </button>
                  ) : (
                    <button
                      onClick={() => void launchSingleBrief(brief)}
                      disabled={startCampaign.isPending || isBatchRunning}
                      className="inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border transition-colors cursor-pointer disabled:opacity-50"
                    >
                      <svg className="w-3 h-3 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <polygon points="5 3 19 12 5 21 5 3" />
                      </svg>
                      <span>Launch This Brief</span>
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="text-[11px] text-muted-foreground flex flex-col sm:flex-row sm:items-center justify-between gap-1 pt-2 border-t border-border/60">
        <span>Runs execute across 5 agents with Cloud Tasks backoff retry protection.</span>
        <span className="font-medium text-foreground/80">Token Efficiency: Status checked at ~5-min intervals during execution</span>
      </div>
    </div>
  );
}
