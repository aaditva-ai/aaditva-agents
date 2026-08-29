import type { StepGroup } from "../api/selectTranscript";
import type { Step } from "../api/types";

/**
 * Purely presentational (plan Step 5): consumes the already-grouped view
 * model from selectTranscript with no reshaping logic of its own --
 * step-card grouping, dedup, and ordering all happened upstream.
 */
export function StepCard({ group }: { group: StepGroup }) {
  return (
    <div className="step-card">
      <div className="step-card-author">{group.author ?? "system"}</div>
      <div className="step-card-body">
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
      return <p className="step-text">{step.text}</p>;
    case "tool_call":
      return <span className="tool-chip tool-chip-call">→ {step.toolName}</span>;
    case "tool_result":
      return (
        <details className="tool-chip tool-chip-result">
          <summary>✓ {step.toolName}</summary>
          <p>{step.text}</p>
        </details>
      );
    case "image":
      return (
        <figure className="image-tile">
          <img src={step.imageUrl} alt={step.text ?? "generated campaign image"} loading="lazy" />
          {step.text && <figcaption>{step.text}</figcaption>}
        </figure>
      );
    case "transfer":
      return <span className="tool-chip tool-chip-transfer">handed off</span>;
    default:
      return null;
  }
}
