import type { StepGroup } from "../api/selectTranscript";
import type { Step } from "../api/types";

/**
 * Purely presentational (plan Step 5): consumes the already-grouped view
 * model from selectTranscript with no reshaping logic of its own --
 * step-card grouping, dedup, and ordering all happened upstream.
 */
export function StepCard({ group }: { group: StepGroup }) {
  return (
    <div className="border border-border bg-card rounded-lg p-3.5 mb-2 shadow-sm" role="region" aria-label={`Step by ${group.author ?? "system"}`}>
      <div className="text-xs text-muted-foreground font-semibold tracking-tight uppercase mb-1.5">{group.author ?? "system"}</div>
      <div className="flex flex-col gap-1.5">
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
      return <p className="text-sm leading-relaxed text-foreground whitespace-pre-wrap">{step.text}</p>;
    case "tool_call":
      return (
        <span
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 text-xs font-medium border border-blue-200 dark:border-blue-900 w-fit"
          aria-label={`Tool call: ${step.toolName}`}
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M8 5l8 6-8 6V5z" />
          </svg>
          <span>{step.toolName}</span>
        </span>
      );
    case "tool_result":
      return (
        <details className="group my-1">
          <summary
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md cursor-pointer text-xs font-medium text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/40 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 border border-emerald-200 dark:border-emerald-900 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2"
            aria-label={`Tool result for ${step.toolName}`}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M20 6L9 17l-5-5" />
            </svg>
            <span>✓ {step.toolName}</span>
          </summary>
          <div className="p-2.5 mt-1.5 text-xs bg-emerald-50/50 dark:bg-emerald-950/20 text-emerald-900 dark:text-emerald-200 rounded-md border border-emerald-200/60 dark:border-emerald-900 font-mono whitespace-pre-wrap break-words">
            {step.text}
          </div>
        </details>
      );
    case "image":
      return (
        <figure className="my-3">
          <img
            src={step.imageUrl}
            alt={step.text ? `Generated campaign asset: ${step.text}` : "Generated campaign visual output"}
            loading="lazy"
            className="rounded-lg border border-border shadow-sm hover:shadow-md transition-shadow max-w-full h-auto"
          />
          {step.text && (
            <figcaption className="mt-1.5 text-xs text-muted-foreground font-medium">
              {step.text}
            </figcaption>
          )}
        </figure>
      );
    case "transfer":
      return (
        <span
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 text-xs font-medium border border-purple-200 dark:border-purple-900 w-fit"
          aria-label="Agent handoff transfer"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="6" cy="6" r="3" />
            <line x1="19" y1="6" x2="6" y2="19" />
            <rect width="8" height="8" x="6" y="6" />
          </svg>
          <span>Handed off</span>
        </span>
      );
    default:
      return null;
  }
}
