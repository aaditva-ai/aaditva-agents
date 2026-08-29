import type { InfiniteData } from "@tanstack/react-query";
import type { CampaignStatus, EventsPage, Step } from "./types";

export interface StepGroup {
  key: string;
  author: string | null;
  invocationId: string | null;
  steps: Step[];
}

export interface Transcript {
  status: CampaignStatus;
  groups: StepGroup[];
}

/**
 * The query's `select` transform (plan Key Decision #7 / Step 5): flattens
 * accumulated cursor pages, dedupes by step `id` (pages can legitimately
 * overlap at the boundary -- see broker/events_normalizer.py's
 * dedupe_by_id, which the broker already applies per-page; this dedupes
 * again across the full accumulated history since two different pages can
 * both contain the same trailing event), and groups consecutive steps by
 * `author` + `invocationId` into step cards (plan Step 5: "group events
 * into step cards keyed by author + invocation_id"). Grouping by author
 * alone would collapse nearly the whole transcript into one card, since
 * real sessions show almost every event after the first is authored by
 * "creative_director" regardless of which specialist it's relaying --
 * invocationId is what actually distinguishes one orchestrator turn from
 * the next. Memoized by TanStack Query per distinct page array reference,
 * so this only re-runs when a new page actually lands -- components read
 * the already-grouped result and do no reshaping of their own.
 */
export function selectTranscript(data: InfiniteData<EventsPage>): Transcript {
  const seen = new Set<string>();
  const steps: Step[] = [];

  for (const page of data.pages) {
    for (const step of page.steps) {
      if (seen.has(step.id)) continue;
      seen.add(step.id);
      steps.push(step);
    }
  }

  // Steps arrive already in chronological order within a page, and pages
  // themselves are appended in poll order, so no explicit sort is needed --
  // only the dedupe above can otherwise cause any reordering risk, and it
  // preserves insertion order.
  const groups: StepGroup[] = [];
  for (const step of steps) {
    const last = groups.at(-1);
    if (last && last.author === step.author && last.invocationId === step.invocationId) {
      last.steps.push(step);
    } else {
      groups.push({ key: step.id, author: step.author, invocationId: step.invocationId, steps: [step] });
    }
  }

  const status = data.pages.at(-1)?.status ?? "starting";

  return { status, groups };
}

export function isTerminal(status: CampaignStatus): boolean {
  return status === "complete" || status === "failed";
}
