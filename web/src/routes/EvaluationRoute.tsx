import { Link } from "react-router-dom";

export function EvaluationRoute() {
  return (
    <div className="space-y-8 animate-fadeIn">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border pb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <span>Evaluation & Rubric Verification</span>
            <span className="text-xs uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
              100% Rubric Auditor
            </span>
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Live infrastructure probing, canonical rubric benchmark runner, and LLM-as-a-Judge grading dashboard.
          </p>
        </div>
        <Link
          to="/"
          className="inline-flex items-center justify-center text-xs font-semibold px-3 py-2 rounded-lg bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border transition-colors self-start sm:self-auto"
        >
          &larr; Back to Campaigns
        </Link>
      </div>

      <div id="eval-content-placeholder" className="p-8 text-center text-muted-foreground border border-dashed rounded-xl">
        Loading evaluation modules...
      </div>
    </div>
  );
}
