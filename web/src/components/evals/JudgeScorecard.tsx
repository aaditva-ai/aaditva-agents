import { useState } from "react";
import { useTriggerJudgeEval, useCampaignEvaluation } from "../../api/queries";
import type { JudgeEvaluationResult, CriterionEval } from "../../api/types";

interface JudgeScorecardProps {
  sessionId?: string;
  initialData?: JudgeEvaluationResult;
  onClose?: () => void;
}

export function JudgeScorecard({ sessionId, initialData, onClose }: JudgeScorecardProps) {
  const { data: fetchedData, isLoading: isQueryLoading, refetch } = useCampaignEvaluation(
    initialData ? undefined : sessionId
  );
  const triggerJudge = useTriggerJudgeEval();
  const [activeCriterionId, setActiveCriterionId] = useState<number | null>(null);

  const evaluation: JudgeEvaluationResult | undefined =
    initialData || (fetchedData?.evaluated !== false ? fetchedData : undefined);

  const isEvaluating = triggerJudge.isPending;

  const handleRunEvaluation = async (force: boolean = false) => {
    if (!sessionId) return;
    try {
      await triggerJudge.mutateAsync({ sessionId, force });
      if (!initialData) {
        void refetch();
      }
    } catch (err) {
      console.error("Failed to run judge evaluation:", err);
    }
  };

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
    <div className="bg-card border border-border rounded-xl p-5 space-y-5 shadow-sm">
      {/* Header with Title and Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border/70">
        <div>
          <div className="flex items-center gap-2.5">
            <h3 className="text-lg font-semibold text-foreground tracking-tight">
              LLM-as-a-Judge Rubric Scorecard
            </h3>
            {evaluation && (
              <span
                className={`text-xs px-2.5 py-0.5 rounded-full font-bold border ${getGradeBadgeColor(
                  evaluation.overallGrade
                )}`}
              >
                {evaluation.overallGrade} ({evaluation.overallScore.toFixed(1)}%)
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            Automated verification against the 7 Capstone Grading Rubric criteria (100% scale).
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          {sessionId && (
            <button
              onClick={() => void handleRunEvaluation(Boolean(evaluation))}
              disabled={isEvaluating}
              className="inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors cursor-pointer shadow-sm"
            >
              <svg
                className={`w-3.5 h-3.5 ${isEvaluating ? "animate-spin" : ""}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
              >
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                <path d="M16 21h5v-5" />
              </svg>
              <span>
                {isEvaluating
                  ? "Auditing Rubric..."
                  : evaluation
                  ? "Re-Run LLM Judge"
                  : "Evaluate with LLM Judge"}
              </span>
            </button>
          )}

          {onClose && (
            <button
              onClick={onClose}
              className="text-xs font-medium px-2.5 py-2 rounded-lg bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border transition-colors cursor-pointer"
            >
              Close
            </button>
          )}
        </div>
      </div>

      {/* Loading state */}
      {(isQueryLoading || isEvaluating) && !evaluation && (
        <div className="py-12 flex flex-col items-center justify-center text-center space-y-3 text-muted-foreground">
          <div className="w-8 h-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
          <p className="text-sm font-medium text-foreground">
            {isEvaluating ? "Auditing transcript with Gemini Rubric Judge..." : "Loading evaluation data..."}
          </p>
          <p className="text-xs text-muted-foreground max-w-sm">
            Evaluating multi-agent orchestration, revision loop, multimodal image generation, and MCP skills.
          </p>
        </div>
      )}

      {/* Empty / Not yet evaluated state */}
      {!evaluation && !isQueryLoading && !isEvaluating && (
        <div className="py-10 text-center space-y-3 bg-muted/20 rounded-xl border border-dashed border-border/80 p-6">
          <div className="w-10 h-10 mx-auto rounded-full bg-primary/10 flex items-center justify-center text-primary">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="m9 11 3 3L22 4" />
              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
            </svg>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-foreground">No Rubric Evaluation Yet</h4>
            <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">
              Run the automated LLM Judge to verify this campaign transcript against all 7 rubric criteria with scorecards and evidence.
            </p>
          </div>
          {sessionId && (
            <button
              onClick={() => void handleRunEvaluation(false)}
              className="inline-flex items-center gap-1.5 text-xs font-semibold px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer shadow-sm"
            >
              Audit This Campaign Now
            </button>
          )}
        </div>
      )}

      {/* Evaluation Results Rendered */}
      {evaluation && (
        <div className="space-y-5">
          {/* Summary Banner & Score Breakdown */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 p-4 rounded-xl bg-muted/30 border border-border/70">
            <div className="md:col-span-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Executive Assessment
                </span>
                <span className="text-[10px] text-muted-foreground font-mono">
                  {new Date(evaluation.evaluatedAt).toLocaleString()}
                </span>
              </div>
              <p className="text-xs text-foreground font-medium leading-relaxed">
                {evaluation.summary}
              </p>
              {evaluation.prompt && (
                <p className="text-[11px] text-muted-foreground font-mono truncate">
                  Prompt: &ldquo;{evaluation.prompt}&rdquo;
                </p>
              )}
            </div>

            <div className="flex flex-col items-center justify-center p-3 rounded-lg bg-background/80 border border-border text-center">
              <span className="text-[11px] uppercase font-bold text-muted-foreground">
                Capstone Total
              </span>
              <span className={`text-2xl font-extrabold ${getScoreColor(evaluation.overallScore)}`}>
                {evaluation.overallScore.toFixed(1)}%
              </span>
              <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded-full mt-1 border ${getGradeBadgeColor(evaluation.overallGrade)}`}>
                {evaluation.overallGrade}
              </span>
            </div>
          </div>

          {/* 7 Criteria Grid */}
          <div className="space-y-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Criterion-by-Criterion Breakdown (100% Weight)
            </h4>

            <div className="space-y-2.5">
              {evaluation.criteria.map((crit) => (
                <CriterionItemCard
                  key={crit.id}
                  criterion={crit}
                  isExpanded={activeCriterionId === crit.id}
                  onToggle={() =>
                    setActiveCriterionId((curr) => (curr === crit.id ? null : crit.id))
                  }
                />
              ))}
            </div>
          </div>

          <div className="p-3 bg-emerald-500/5 border border-emerald-500/20 rounded-lg text-[11px] text-muted-foreground flex items-center justify-between">
            <span className="text-emerald-500 font-semibold">
              ✓ All 7 Rubric Criteria Audited
            </span>
            <span>Evaluation cached in Firestore to conserve AI tokens</span>
          </div>
        </div>
      )}
    </div>
  );
}

function CriterionItemCard({
  criterion,
  isExpanded,
  onToggle,
}: {
  criterion: CriterionEval;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const percentWeight = Math.round(criterion.weight * 100);

  return (
    <div
      className={`border rounded-xl transition-all ${
        isExpanded
          ? "border-primary/50 bg-card shadow-sm"
          : "border-border/70 bg-background/50 hover:bg-muted/30"
      }`}
    >
      <div
        onClick={onToggle}
        className="p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 cursor-pointer select-none"
      >
        <div className="flex items-start sm:items-center gap-2.5 min-w-0">
          <span className="w-6 h-6 rounded-full bg-muted flex items-center justify-center text-xs font-mono font-bold text-muted-foreground shrink-0">
            {criterion.id}
          </span>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground flex flex-wrap items-center gap-2">
              <span>{criterion.name}</span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                Weight: {percentWeight}%
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
              {criterion.rationale}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0 self-end sm:self-center">
          <div className="text-right">
            <div className="text-sm font-bold font-mono text-foreground">
              {criterion.score} / 100
            </div>
            <span
              className={`text-[10px] uppercase font-bold px-1.5 py-0.2 rounded border ${
                criterion.passed
                  ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
                  : "bg-rose-500/10 text-rose-500 border-rose-500/20"
              }`}
            >
              {criterion.rating}
            </span>
          </div>

          <svg
            className={`w-4 h-4 text-muted-foreground transition-transform ${
              isExpanded ? "rotate-180" : ""
            }`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </div>
      </div>

      {isExpanded && (
        <div className="p-4 bg-muted/30 border-t border-border/70 rounded-b-xl space-y-3 text-xs">
          <div>
            <h5 className="font-semibold text-foreground mb-1">Judge Rationale:</h5>
            <p className="text-muted-foreground leading-relaxed">{criterion.rationale}</p>
          </div>

          {criterion.evidence && criterion.evidence.length > 0 && (
            <div>
              <h5 className="font-semibold text-foreground mb-1.5">Qualitative Evidence & Observations:</h5>
              <ul className="space-y-1.5 text-muted-foreground">
                {criterion.evidence.map((ev, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-primary font-bold shrink-0">•</span>
                    <span>{ev}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
