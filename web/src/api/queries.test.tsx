import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import {
  useCampaignEvents,
  useAgentHealth,
  useBenchmarkBriefs,
  useTriggerJudgeEval,
  useUserAverageEvaluation,
} from "./queries";
import * as authedFetchModule from "./authedFetch";
import type {
  EventsPage,
  AgentHealthReport,
  BenchmarkBrief,
  JudgeEvaluationResult,
  AverageEvaluationReport,
} from "./types";

/**
 * Regression coverage for the bug caught during Step 5 build/validation:
 * TanStack Query's automatic `refetchInterval` on a useInfiniteQuery does
 * NOT advance the cursor -- it re-fetches existing pages from page 0 with
 * their *original* params (see @tanstack/query-core's
 * infiniteQueryBehavior.ts). useCampaignEvents must poll by calling
 * fetchNextPage() on an interval instead. These tests assert on the
 * observable contract (authedFetch is called with successively later
 * `since` values as pages accumulate), not on TanStack Query's internals.
 */

function makePage(cursor: string | null, status: EventsPage["status"] = "running", stepCount = 0): EventsPage {
  return {
    cursor,
    status,
    steps: Array.from({ length: stepCount }, (_, i) => ({
      id: `${cursor ?? "0"}:${i}`,
      author: "user",
      invocationId: "inv-1",
      kind: "text" as const,
      text: `step ${i}`,
      timestamp: cursor,
    })),
  };
}

function wrapper(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useCampaignEvents polling", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  afterEach(() => {
    vi.useRealTimers();
    queryClient.clear();
  });

  it("advances the cursor on each poll tick instead of re-fetching page 0", async () => {
    const authedFetch = vi.spyOn(authedFetchModule, "authedFetch");
    authedFetch
      .mockResolvedValueOnce(makePage("t1"))
      .mockResolvedValueOnce(makePage("t2"))
      .mockResolvedValueOnce(makePage("t3"));

    const { result } = renderHook(() => useCampaignEvents("session-1"), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(authedFetch).toHaveBeenNthCalledWith(1, "/campaigns/session-1/events");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(authedFetch).toHaveBeenNthCalledWith(2, "/campaigns/session-1/events?since=t1");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(authedFetch).toHaveBeenNthCalledWith(3, "/campaigns/session-1/events?since=t2");
  });

  it("stops polling once the campaign reaches a terminal status", async () => {
    const authedFetch = vi.spyOn(authedFetchModule, "authedFetch");
    authedFetch.mockResolvedValueOnce(makePage("t1", "complete"));

    const { result } = renderHook(() => useCampaignEvents("session-1"), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.data?.status).toBe("complete"));
    const callsAtCompletion = authedFetch.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    expect(authedFetch.mock.calls.length).toBe(callsAtCompletion);
  });

  it("keeps polling while stalled, since a stall can resolve on its own", async () => {
    const authedFetch = vi.spyOn(authedFetchModule, "authedFetch");
    authedFetch
      .mockResolvedValueOnce(makePage("t1", "stalled"))
      .mockResolvedValue(makePage("t2", "running")); // stays "running" for any further ticks

    const { result } = renderHook(() => useCampaignEvents("session-1"), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.data?.status).toBe("stalled"));
    const callsWhileStalled = authedFetch.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    // The core assertion: polling continued past "stalled" (a second call
    // actually happened) rather than the interval treating it as terminal.
    await waitFor(() => expect(authedFetch.mock.calls.length).toBeGreaterThan(callsWhileStalled));
    await waitFor(() => expect(result.current.data?.status).toBe("running"));
  });
});

describe("Evaluation API queries", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  afterEach(() => {
    queryClient.clear();
  });

  it("useAgentHealth fetches health report from /evals/health", async () => {
    const mockReport: AgentHealthReport = {
      timestamp: "2026-09-01T12:00:00Z",
      allHealthy: true,
      services: [
        {
          id: "brand_strategist",
          name: "Brand Strategist",
          description: "Strategist",
          url: "http://localhost:8082",
          status: "online",
          statusCode: 200,
          latencyMs: 50,
        },
      ],
    };

    const authedFetch = vi.spyOn(authedFetchModule, "authedFetch").mockResolvedValueOnce(mockReport);

    const { result } = renderHook(() => useAgentHealth(), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(authedFetch).toHaveBeenCalledWith("/evals/health");
    expect(result.current.data?.allHealthy).toBe(true);
    expect(result.current.data?.services.length).toBe(1);
  });

  it("useBenchmarkBriefs fetches benchmarks catalog from /evals/benchmarks", async () => {
    const mockBriefs: BenchmarkBrief[] = [
      {
        id: "smart-water-bottle",
        title: "Smart Water Bottle",
        prompt: "Instagram campaign...",
        category: "Full Pipeline",
        focus: "All 5 specialists",
        targetRubricCriterion: "Criterion 1",
        expectedRounds: 1,
        cooldownSeconds: 15,
      },
    ];

    const authedFetch = vi
      .spyOn(authedFetchModule, "authedFetch")
      .mockResolvedValueOnce({ benchmarks: mockBriefs });

    const { result } = renderHook(() => useBenchmarkBriefs(), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(authedFetch).toHaveBeenCalledWith("/evals/benchmarks");
    expect(result.current.data?.length).toBe(1);
    expect(result.current.data?.[0].id).toBe("smart-water-bottle");
  });

  it("useTriggerJudgeEval triggers evaluation and seeds query cache", async () => {
    const mockEvalResult: JudgeEvaluationResult = {
      sessionId: "sess-judge-1",
      evaluatedAt: "2026-09-01T12:00:00Z",
      overallScore: 100.0,
      overallGrade: "Excellent",
      summary: "Met all criteria",
      criteria: [
        {
          id: 1,
          name: "Multi-Agent Orchestration",
          weight: 0.20,
          score: 100,
          rating: "Excellent",
          passed: true,
          rationale: "Clean orchestration",
          evidence: ["Sequenced specialists"],
        },
      ],
    };

    const authedFetch = vi
      .spyOn(authedFetchModule, "authedFetch")
      .mockResolvedValueOnce(mockEvalResult);

    const { result } = renderHook(() => useTriggerJudgeEval(), {
      wrapper: wrapper(queryClient),
    });

    let mutateRes: JudgeEvaluationResult | undefined;
    await act(async () => {
      mutateRes = await result.current.mutateAsync({ sessionId: "sess-judge-1" });
    });

    expect(authedFetch).toHaveBeenCalledWith("/evals/judge", {
      method: "POST",
      body: JSON.stringify({ sessionId: "sess-judge-1" }),
    });
    expect(mutateRes?.overallScore).toBe(100.0);
    const cached = queryClient.getQueryData(["campaign", "sess-judge-1", "evaluation"]);
    expect(cached).toEqual(mockEvalResult);
  });

  it("useUserAverageEvaluation fetches the aggregate scorecard from /evals/average", async () => {
    const mockReport: AverageEvaluationReport = {
      userId: "user-123",
      totalRunCount: 3,
      evaluatedRunCount: 2,
      averageScore: 87.5,
      averageGrade: "Good",
      criteria: [
        { id: 1, name: "Multi-Agent Orchestration & Workflow", weight: 0.2, averageScore: 87.5 },
      ],
      generatedAt: "2026-09-01T12:00:00Z",
    };

    const authedFetch = vi.spyOn(authedFetchModule, "authedFetch").mockResolvedValueOnce(mockReport);

    const { result } = renderHook(() => useUserAverageEvaluation(), {
      wrapper: wrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(authedFetch).toHaveBeenCalledWith("/evals/average");
    expect(result.current.data?.averageScore).toBe(87.5);
    expect(result.current.data?.evaluatedRunCount).toBe(2);
  });
});
