import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useCampaignEvents } from "./queries";
import * as authedFetchModule from "./authedFetch";
import type { EventsPage } from "./types";

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
