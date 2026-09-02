import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient, useInfiniteQuery } from "@tanstack/react-query";
import { authedFetch, ApiError } from "./authedFetch";
import type {
  CampaignSummary,
  EventsPage,
  AgentHealthReport,
  BenchmarkBrief,
  JudgeEvaluationResult,
  QuotaStatusResponse,
} from "./types";
import { selectTranscript, isTerminal } from "./selectTranscript";

/**
 * The client's entire server-state surface (plan Key Decision #6 / Step 4).
 * No component talks to authedFetch directly -- every broker call is one of
 * the three hooks below, so retry/backoff/refetch policy lives in one
 * place (the QueryClient defaults in main.tsx) rather than scattered
 * per-component logic.
 */

export async function createCampaign(prompt: string): Promise<{ sessionId: string }> {
  return authedFetch("/campaigns", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  }) as Promise<{ sessionId: string }>;
}

export function useStartCampaign() {
  const queryClient = useQueryClient();
  return useMutation<{ sessionId: string }, ApiError, string>({
    mutationFn: createCampaign,
    onSuccess: ({ sessionId }) => {
      // Seed the events cache with a "starting" placeholder so the very
      // first render of /c/:sessionId (before the first real poll lands)
      // shows an explicit starting state rather than a blank/loading flash
      // (plan Functional Requirement 1).
      queryClient.setQueryData(["campaign", sessionId, "events"], {
        pages: [{ cursor: null, status: "starting", steps: [] } satisfies EventsPage],
        pageParams: [undefined],
      });
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });
}

async function fetchCampaigns(): Promise<{ campaigns: CampaignSummary[] }> {
  return authedFetch("/campaigns") as Promise<{ campaigns: CampaignSummary[] }>;
}

export function useCampaigns() {
  return useQuery({
    queryKey: ["campaigns"],
    queryFn: fetchCampaigns,
    select: (data) => data.campaigns,
    refetchOnWindowFocus: true,
  });
}

async function fetchEvents(sessionId: string, since: string | null | undefined): Promise<EventsPage> {
  const query = since ? `?since=${encodeURIComponent(since)}` : "";
  return authedFetch(`/campaigns/${sessionId}/events${query}`) as Promise<EventsPage>;
}

async function resumeCampaign(sessionId: string): Promise<{ sessionId: string }> {
  return authedFetch(`/campaigns/${sessionId}/resume`, { method: "POST" }) as Promise<{
    sessionId: string;
  }>;
}

/** Plan Step 6: re-drives a failed/stalled campaign, subject to the same
 * per-user limits as starting a new one. Invalidates the events query so
 * the next poll picks up the fresh "running" status instead of waiting out
 * the existing refetchInterval.
 */
export function useResumeCampaign(sessionId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation<{ sessionId: string }, ApiError, void>({
    mutationFn: () => {
      if (!sessionId) throw new Error("No session ID");
      return resumeCampaign(sessionId);
    },
    onSuccess: () => {
      if (sessionId) {
        queryClient.invalidateQueries({ queryKey: ["campaign", sessionId, "events"] });
      }
    },
  });
}

const POLL_INTERVAL_MS = 2000;

/**
 * Polls a campaign's transcript by repeatedly calling fetchNextPage(), not
 * TanStack Query's automatic `refetchInterval`.
 *
 * `refetchInterval`/plain refetch() on a useInfiniteQuery re-runs every
 * already-fetched page from page 0 with its *original* page params -- it
 * does not advance the cursor (see @tanstack/query-core's
 * infiniteQueryBehavior.ts: a refetch with no `fetchMore` direction always
 * refetches from `oldPageParams[0]`, i.e. the first page's original
 * `since`). Only fetchNextPage() passes `meta.fetchMore.direction:
 * 'forward'`, which is what makes the library fetch a genuinely new page
 * using getNextPageParam's result. This is why the plan's original
 * reference snippet (a bare `refetchInterval` on useInfiniteQuery) would
 * not actually poll forward in practice -- see the Decisions section for
 * Step 5 in docs/replace-gradio-with-spa-job-architecture.md.
 *
 * broker/main.py's `cursor` is also guaranteed non-null once a campaign
 * exists (falls back to "now" when there are no events yet), so
 * getNextPageParam here never returns null while polling should continue
 * -- a null page param on an existing page would make fetchNextPage() a
 * no-op (see infiniteQueryBehavior.ts's `param == null && data.pages.length`
 * early-return), silently freezing the poll.
 */
export function useCampaignEvents(sessionId: string | undefined) {
  const query = useInfiniteQuery({
    queryKey: ["campaign", sessionId, "events"],
    queryFn: ({ pageParam }) => {
      if (!sessionId) throw new Error("No session ID");
      return fetchEvents(sessionId, pageParam);
    },
    enabled: Boolean(sessionId),
    initialPageParam: undefined as string | null | undefined,
    getNextPageParam: (lastPage) => lastPage.cursor,
    select: selectTranscript,
    refetchOnWindowFocus: false, // a focus-triggered refetch() would hit the same re-fetch-from-page-0 issue
    retry: 5,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 30_000),
  });

  const status = query.data?.status;
  const { fetchNextPage, isFetchingNextPage } = query;

  useEffect(() => {
    if (!sessionId) return;
    if (isTerminal(status ?? "starting")) return;
    // "stalled" keeps polling deliberately, since a stall can resolve on
    // its own (e.g. a slow specialist call finally returns) and the only
    // way to notice is to keep asking (plan Functional Requirement 5).
    // Document visibility gating (pausing while the tab is hidden) is
    // handled by the browser's own setInterval throttling in background
    // tabs, matching refetchIntervalInBackground: false's intent without
    // needing that (inapplicable, refetchInterval-only) option here.
    const id = window.setInterval(() => {
      if (!isFetchingNextPage) void fetchNextPage();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [sessionId, status, fetchNextPage, isFetchingNextPage]);

  return query;
}

// ---- Evaluation Dashboard & LLM Judge Hooks ----

async function fetchAgentHealth(): Promise<AgentHealthReport> {
  return authedFetch("/evals/health") as Promise<AgentHealthReport>;
}

export function useAgentHealth(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["evals", "health"],
    queryFn: fetchAgentHealth,
    enabled: options?.enabled ?? true,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
}

async function fetchBenchmarkBriefs(): Promise<{ benchmarks: BenchmarkBrief[] }> {
  return authedFetch("/evals/benchmarks") as Promise<{ benchmarks: BenchmarkBrief[] }>;
}

export function useBenchmarkBriefs() {
  return useQuery({
    queryKey: ["evals", "benchmarks"],
    queryFn: fetchBenchmarkBriefs,
    select: (data) => data.benchmarks,
    staleTime: 5 * 60_000,
  });
}

async function triggerJudgeEval(params: {
  sessionId: string;
  force?: boolean;
}): Promise<JudgeEvaluationResult> {
  return authedFetch("/evals/judge", {
    method: "POST",
    body: JSON.stringify(params),
  }) as Promise<JudgeEvaluationResult>;
}

export function useTriggerJudgeEval() {
  const queryClient = useQueryClient();
  return useMutation<JudgeEvaluationResult, ApiError, { sessionId: string; force?: boolean }>({
    mutationFn: triggerJudgeEval,
    onSuccess: (data, variables) => {
      queryClient.setQueryData(["campaign", variables.sessionId, "evaluation"], data);
    },
  });
}

async function fetchCampaignEvaluation(sessionId: string): Promise<JudgeEvaluationResult> {
  return authedFetch(`/evals/campaigns/${sessionId}`) as Promise<JudgeEvaluationResult>;
}

export function useCampaignEvaluation(sessionId: string | undefined) {
  return useQuery({
    queryKey: ["campaign", sessionId, "evaluation"],
    queryFn: () => {
      if (!sessionId) throw new Error("No session ID");
      return fetchCampaignEvaluation(sessionId);
    },
    enabled: Boolean(sessionId),
    staleTime: 60_000,
  });
}

async function prepareImageQuotas(): Promise<QuotaStatusResponse> {
  return authedFetch("/evals/prepare-quotas", { method: "POST" }) as Promise<QuotaStatusResponse>;
}

export function usePrepareImageQuotas() {
  return useMutation<QuotaStatusResponse, ApiError, void>({
    mutationFn: prepareImageQuotas,
  });
}
