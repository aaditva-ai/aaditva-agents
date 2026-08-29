import { describe, expect, it } from "vitest";
import type { InfiniteData } from "@tanstack/react-query";
import { selectTranscript, isTerminal } from "./selectTranscript";
import type { EventsPage, Step } from "./types";

function step(overrides: Partial<Step> & Pick<Step, "id" | "author" | "invocationId" | "kind">): Step {
  return { timestamp: null, ...overrides };
}

function page(overrides: Partial<EventsPage>): EventsPage {
  return { cursor: null, status: "running", steps: [], ...overrides };
}

function infinite(pages: EventsPage[]): InfiniteData<EventsPage> {
  return { pages, pageParams: pages.map(() => undefined) };
}

describe("selectTranscript", () => {
  it("flattens a single page into one group per author+invocationId run", () => {
    const p = page({
      status: "running",
      steps: [
        step({ id: "1:0", author: "user", invocationId: "inv-1", kind: "text", text: "hi" }),
        step({ id: "2:0", author: "creative_director", invocationId: "inv-1", kind: "text", text: "hello" }),
        step({ id: "2:1", author: "creative_director", invocationId: "inv-1", kind: "tool_call", toolName: "brand_strategist" }),
      ],
    });

    const result = selectTranscript(infinite([p]));

    expect(result.status).toBe("running");
    expect(result.groups).toHaveLength(2);
    expect(result.groups[0].steps.map((s) => s.id)).toEqual(["1:0"]);
    expect(result.groups[1].steps.map((s) => s.id)).toEqual(["2:0", "2:1"]);
  });

  it("accumulates steps across multiple pages in order", () => {
    const page1 = page({ steps: [step({ id: "1:0", author: "user", invocationId: "inv-1", kind: "text" })] });
    const page2 = page({
      status: "complete",
      steps: [step({ id: "2:0", author: "creative_director", invocationId: "inv-1", kind: "text" })],
    });

    const result = selectTranscript(infinite([page1, page2]));

    expect(result.groups.flatMap((g) => g.steps.map((s) => s.id))).toEqual(["1:0", "2:0"]);
    // status reflects the *latest* page, since that's the most current poll result
    expect(result.status).toBe("complete");
  });

  it("dedupes a step id that appears in more than one page (overlapping cursor pages)", () => {
    const page1 = page({ steps: [step({ id: "1:0", author: "user", invocationId: "inv-1", kind: "text" })] });
    const page2 = page({
      steps: [
        step({ id: "1:0", author: "user", invocationId: "inv-1", kind: "text" }),
        step({ id: "2:0", author: "creative_director", invocationId: "inv-1", kind: "text" }),
      ],
    });

    const result = selectTranscript(infinite([page1, page2]));

    const allIds = result.groups.flatMap((g) => g.steps.map((s) => s.id));
    expect(allIds).toEqual(["1:0", "2:0"]);
  });

  it("splits consecutive same-author steps into separate groups when invocationId differs", () => {
    const p = page({
      steps: [
        step({ id: "1:0", author: "creative_director", invocationId: "inv-1", kind: "text" }),
        step({ id: "2:0", author: "creative_director", invocationId: "inv-2", kind: "text" }),
      ],
    });

    const result = selectTranscript(infinite([p]));

    expect(result.groups).toHaveLength(2);
  });

  it("defaults status to 'starting' when there are no pages worth of data yet", () => {
    const result = selectTranscript(infinite([page({ status: "starting", steps: [] })]));
    expect(result.status).toBe("starting");
    expect(result.groups).toEqual([]);
  });

  it("is referentially stable in shape across two calls with identical input (memoization contract)", () => {
    const data = infinite([page({ steps: [step({ id: "1:0", author: "user", invocationId: "inv-1", kind: "text" })] })]);
    const first = selectTranscript(data);
    const second = selectTranscript(data);
    // Not asserting reference equality (TanStack Query itself handles the
    // memoization by page-array identity) -- asserting the transform is
    // pure/deterministic: same input always produces an equivalent result.
    expect(second).toEqual(first);
  });
});

describe("isTerminal", () => {
  it("is true for complete and failed, false otherwise", () => {
    expect(isTerminal("complete")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
    expect(isTerminal("running")).toBe(false);
    expect(isTerminal("starting")).toBe(false);
    expect(isTerminal("stalled")).toBe(false);
  });
});
