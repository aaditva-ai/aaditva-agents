import type { StepGroup } from "../api/selectTranscript";
import type { Step } from "../api/types";

/**
 * Purely presentational (plan Step 5): consumes the already-grouped view
 * model from selectTranscript with no reshaping logic of its own --
 * step-card grouping, dedup, and ordering all happened upstream.
 */
export function StepCard({ group }: { group: StepGroup }) {
  return (
    <div className="border border-border bg-card rounded-lg p-3 mb-2 shadow-sm">
      <div className="text-xs text-muted-foreground font-medium tracking-tight uppercase mb-1">{group.author ?? "system"}</div>
      <div className="flex flex-col gap-0">
        {group.steps.map((step) => (
          <StepView key={step.id} step={step} />
        ))}
      </div>
    </div>
  );
}

function StepView({ step }: { step: Step }) {
  switch (step.kind) {
    case "text":
      return <p className="text-sm leading-relaxed text-foreground">{step.text}</p>;
    case "tool_call":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-blue-50 text-blue-700 text-xs font-medium border border-blue-100 hover:bg-blue-100 transition-colors">
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 5l8 6-8 6V5z"/></svg>
          {step.toolName}
        </span>
      );
    case "tool_result":
      return (
        <details className="group">
          <summary className="inline-flex items-center gap-1 px-2 py-0.5 rounded cursor-pointer text-xs font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 aria-expanded:bg-emerald-100">
            <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5"/></svg>
            ✓ {step.toolName}
          </summary>
          <div className="p-2 mt-1 text-xs bg-emerald-50/50 rounded border border-emerald-100">{step.text}</div>
        </details>
      );
    case "image":
      return (
        <figure className="my-2">
          <img src={step.imageUrl} alt={step.text ?? "generated campaign image"} loading="lazy" className="rounded-lg border border-border shadow-sm hover:shadow-md transition-shadow" />
          {step.text && <figcaption className="mt-1 text-xs text-muted-foreground">{step.text}</figcaption>}
        </figure>
      );
    case "transfer":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-purple-50 text-purple-700 text-xs font-medium border border-purple-100 hover:bg-purple-100 transition-colors">
          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="6" cy="6" r="3"/><line x1="19" y1="6" x2="6" y2="19"/><rect width="8" height="8" x="6" y="6"/></svg>
          Handed off
        </span>
      );
    default:
      return null;
  }
}
