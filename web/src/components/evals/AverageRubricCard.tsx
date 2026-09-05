import { useUserAverageEvaluation } from "../../api/queries";

/**
 * The average-across-all-runs section, rendered above BenchmarkBriefsCard's
 * per-brief runs list (Evaluation Dashboard). Unlike JudgeScorecard, which
 * shows one campaign's rubric scorecard, this aggregates every cached LLM
 * Judge evaluation for the signed-in user via GET /evals/average.
 */
export function AverageRubricCard() {
  const { data: report, isLoading, isError } = useUserAverageEvaluation();

  const getGradeBadgeColor = (grade: string) => {
    switch (grade) {
      case "Excellent":
        return "bg-emerald-500/10 text-emerald-500 border-emerald-500/20";
      case "Good":
        return "bg-blue-500/10 text-blue-500 border-blue-500/20";
      case "Developing":
        return "bg-amber-500/10 text-amber-500 border-amber-500/20";
      default:
        return "bg-rose-500/10 text-rose-500 border-rose-500/20";
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 90) return "text-emerald-500";
    if (score >= 75) return "text-blue-500";
    if (score >= 50) return "text-amber-500";
    return "text-rose-500";
  };

  return (
    <div className="bg-card border border-border rounded-xl p-5 space-y-4 shadow-sm">
      <div className="pb-3 border-b border-border/70">
        <h3 className="text-lg font-semibold text-foreground tracking-tight">
          Average Rubric Score Across All Runs
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          Aggregated LLM-as-a-Judge results across every campaign run you have generated and evaluated so far.
        </p>
      </div>

      {isLoading && (
        <div className="py-8 flex flex-col items-center justify-center text-center space-y-3 text-muted-foreground">
          <div className="w-6 h-6 rounded-full border-2 border-primary border-t-transparent animate-spin" />
          <p className="text-xs text-muted-foreground">Loading average rubric measurements...</p>
        </div>
      )}

      {isError && !isLoading && (
        <div className="p-4 text-center text-xs text-rose-500 bg-rose-500/5 border border-dashed border-rose-500/20 rounded-xl">
          Could not load your average rubric measurements. Please try again later.
        </div>
      )}

      {!isLoading && !isError && report && report.evaluatedRunCount === 0 && (
        <div className="p-6 text-center text-xs text-muted-foreground bg-muted/20 border border-dashed border-border rounded-xl">
          No evaluated campaign runs yet. Run the LLM Judge on a completed campaign to start building your average.
        </div>
      )}

      {!isLoading && !isError && report && report.evaluatedRunCount > 0 && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 p-4 rounded-xl bg-muted/30 border border-border/70">
            <div className="md:col-span-3 space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                Signed-In User Summary
              </span>
              <p className="text-xs text-foreground font-medium leading-relaxed">
                Averaged across {report.evaluatedRunCount} evaluated campaign run
                {report.evaluatedRunCount === 1 ? "" : "s"} out of {report.totalRunCount} total run
                {report.totalRunCount === 1 ? "" : "s"}.
              </p>
            </div>

            <div className="flex flex-col items-center justify-center p-3 rounded-lg bg-background/80 border border-border text-center">
              <span className="text-[11px] uppercase font-bold text-muted-foreground">Average Score</span>
              <span className={`text-2xl font-extrabold ${getScoreColor(report.averageScore)}`}>
                {report.averageScore.toFixed(1)}%
              </span>
              <span
                className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded-full mt-1 border ${getGradeBadgeColor(
                  report.averageGrade
                )}`}
              >
                {report.averageGrade}
              </span>
            </div>
          </div>

          {report.criteria.length > 0 && (
            <div className="space-y-2.5">
              <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                Average Criterion-by-Criterion Breakdown
              </h4>

              <div className="space-y-2">
                {report.criteria.map((crit) => (
                  <div
                    key={crit.id}
                    className="border border-border/70 bg-background/50 rounded-xl p-3.5 flex items-center justify-between gap-3"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className="w-6 h-6 rounded-full bg-muted flex items-center justify-center text-xs font-mono font-bold text-muted-foreground shrink-0">
                        {crit.id}
                      </span>
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-foreground flex flex-wrap items-center gap-2">
                          <span>{crit.name}</span>
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                            Weight: {Math.round(crit.weight * 100)}%
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className={`text-sm font-bold font-mono shrink-0 ${getScoreColor(crit.averageScore)}`}>
                      {crit.averageScore.toFixed(1)} / 100
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
