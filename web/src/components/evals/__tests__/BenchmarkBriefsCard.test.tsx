import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { BenchmarkBriefsCard } from "../BenchmarkBriefsCard";
import * as queries from "../../../api/queries";
import type { BenchmarkBrief, CampaignSummary, JudgeEvaluationResult } from "../../../api/types";

const mockBenchmarks: BenchmarkBrief[] = [
  {
    id: "smart-water-bottle",
    title: "Smart Water Bottle for Millennials",
    prompt: "Instagram campaign for a smart water bottle for health-conscious millennials",
    category: "Full Pipeline",
    focus: "The built-in default: exercises all 5 agents end-to-end",
    targetRubricCriterion: "Criterion 1 (Multi-Agent Orchestration & Workflow)",
    expectedRounds: 1,
    cooldownSeconds: 15,
  },
  {
    id: "sustainable-sneakers",
    title: "Sustainable Sneaker Brand for Gen Z",
    prompt: "Launch a sustainable sneaker brand for Gen Z, eco and street-style angle",
    category: "Audience & Concept",
    focus: "Audience research plus a distinct visual concept and aesthetic tone",
    targetRubricCriterion: "Criterion 1 (Orchestration) & Criterion 4 (Multimodal Image Gen)",
    expectedRounds: 1,
    cooldownSeconds: 15,
  },
];

const mockCampaigns: CampaignSummary[] = [
  {
    sessionId: "session-smart-bottle-1",
    title: "Instagram campaign for a smart water bottle for health-conscious millennials",
    prompt: "Instagram campaign for a smart water bottle for health-conscious millennials",
    status: "complete",
    createdAt: "2026-09-01T10:00:00Z",
    lastEventAt: "2026-09-01T10:05:00Z",
  },
];

const mockEvaluation: JudgeEvaluationResult = {
  sessionId: "session-smart-bottle-1",
  evaluatedAt: "2026-09-01T10:06:00Z",
  prompt: "Instagram campaign for a smart water bottle for health-conscious millennials",
  overallScore: 98.0,
  overallGrade: "Excellent",
  summary: "Outstanding full pipeline execution.",
  criteria: [],
};

describe("BenchmarkBriefsCard Component", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    localStorage.clear();
    sessionStorage.clear();

    vi.spyOn(queries, "useBenchmarkBriefs").mockReturnValue({
      data: mockBenchmarks,
      isLoading: false,
      error: null,
    } as any);

    vi.spyOn(queries, "useCampaigns").mockReturnValue({
      data: mockCampaigns,
      isLoading: false,
      error: null,
    } as any);

    vi.spyOn(queries, "useCampaignEvaluation").mockImplementation(((sessionId: string | undefined) => {
      if (sessionId === "session-smart-bottle-1") {
        return { data: mockEvaluation, isLoading: false, error: null } as any;
      }
      return { data: undefined, isLoading: false, error: null } as any;
    }) as any);

    vi.spyOn(queries, "useStartCampaign").mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as any);
  });

  it("renders benchmark cards with titles, prompts, and single launch buttons without parallel controls", () => {
    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <BenchmarkBriefsCard />
        </QueryClientProvider>
      </MemoryRouter>
    );

    expect(screen.getByText(/Curated Rubric Benchmark Briefs/i)).toBeDefined();
    // Parallel buttons should NOT exist
    expect(screen.queryByText(/Run All Benchmarks/i)).toBeNull();
    expect(screen.queryByText(/All \(5 Parallel\)/i)).toBeNull();
    expect(screen.queryByText(/3 Parallel/i)).toBeNull();
    expect(screen.queryByText(/2 Parallel/i)).toBeNull();
    expect(screen.queryByText(/Sequential \(1-by-1\)/i)).toBeNull();
    expect(screen.queryByText(/GenAI Image Quota Scaling/i)).toBeNull();

    // Benchmark titles and prompts are rendered
    expect(screen.getAllByText(/Smart Water Bottle for Millennials/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Sustainable Sneaker Brand for Gen Z/i).length).toBeGreaterThan(0);
  });

  it("shows last evaluation score and Re-run Brief button for previously run briefs when idle", () => {
    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <BenchmarkBriefsCard />
        </QueryClientProvider>
      </MemoryRouter>
    );

    // Smart water bottle was previously run & evaluated
    const rerunBtn = screen.getByRole("button", { name: /Re-run Brief/i });
    expect(rerunBtn).toBeDefined();
    expect(rerunBtn.hasAttribute("disabled")).toBe(false);
    expect(screen.getByText(/Last Evaluation:/i)).toBeDefined();
    expect(screen.getByText(/98.0%/i)).toBeDefined();
    expect(screen.getByText(/View Rubric Audit/i)).toBeDefined();

    // Sustainable sneakers was not run yet
    const launchBtn = screen.getByRole("button", { name: /Launch This Brief/i });
    expect(launchBtn).toBeDefined();
    expect(launchBtn.hasAttribute("disabled")).toBe(false);
  });

  it("renders View Live Run link opening in a new tab", () => {
    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <BenchmarkBriefsCard />
        </QueryClientProvider>
      </MemoryRouter>
    );

    const liveRunLink = screen.getByRole("link", { name: /View Live Run/i });
    expect(liveRunLink.getAttribute("target")).toBe("_blank");
    expect(liveRunLink.getAttribute("href")).toBe("/c/session-smart-bottle-1");
  });

  it("disables both Launch and Re-run buttons with a hovertip when a campaign is running", () => {
    const runningCampaigns: CampaignSummary[] = [
      {
        sessionId: "session-smart-bottle-1",
        title: "Instagram campaign for a smart water bottle for health-conscious millennials",
        prompt: "Instagram campaign for a smart water bottle for health-conscious millennials",
        status: "running",
        createdAt: "2026-09-01T10:00:00Z",
        lastEventAt: "2026-09-01T10:05:00Z",
      },
    ];

    vi.spyOn(queries, "useCampaigns").mockReturnValue({
      data: runningCampaigns,
      isLoading: false,
      error: null,
    } as any);

    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <BenchmarkBriefsCard />
        </QueryClientProvider>
      </MemoryRouter>
    );

    expect(screen.getByText(/Campaign in progress — other launches disabled/i)).toBeDefined();

    const rerunBtn = screen.getByRole("button", { name: /Re-run Brief/i });
    expect(rerunBtn.hasAttribute("disabled")).toBe(true);
    expect(rerunBtn.getAttribute("title")).toMatch(/Cannot launch while a campaign run is currently in progress/i);

    const launchBtn = screen.getByRole("button", { name: /Launch This Brief/i });
    expect(launchBtn.hasAttribute("disabled")).toBe(true);
    expect(launchBtn.getAttribute("title")).toMatch(/Cannot launch while a campaign run is currently in progress/i);
  });

  it("disables Launch and Re-run buttons when a campaign is dispatched", () => {
    const dispatchedCampaigns: CampaignSummary[] = [
      ...mockCampaigns,
      {
        sessionId: "session-other-1",
        title: "Other campaign",
        prompt: "Other prompt",
        status: "dispatched",
        createdAt: "2026-09-01T10:00:00Z",
        lastEventAt: "2026-09-01T10:01:00Z",
      },
    ];

    vi.spyOn(queries, "useCampaigns").mockReturnValue({
      data: dispatchedCampaigns,
      isLoading: false,
      error: null,
    } as any);

    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <BenchmarkBriefsCard />
        </QueryClientProvider>
      </MemoryRouter>
    );

    const rerunBtn = screen.getByRole("button", { name: /Re-run Brief/i });
    expect(rerunBtn.hasAttribute("disabled")).toBe(true);

    const launchBtn = screen.getByRole("button", { name: /Launch This Brief/i });
    expect(launchBtn.hasAttribute("disabled")).toBe(true);
  });

  it("renders Evaluate Rubric button and calls mutateAsync when campaign is completed without evaluation", async () => {
    const unevaluatedCampaigns: CampaignSummary[] = [
      {
        sessionId: "session-sneakers-1",
        title: "Sustainable Sneaker Brand for Gen Z",
        prompt: "Launch a sustainable sneaker brand for Gen Z, eco and street-style angle",
        status: "complete",
        createdAt: "2026-09-01T10:00:00Z",
        lastEventAt: "2026-09-01T10:05:00Z",
      },
    ];

    vi.spyOn(queries, "useCampaigns").mockReturnValue({
      data: unevaluatedCampaigns,
      isLoading: false,
      error: null,
    } as any);

    const mutateAsyncMock = vi.fn().mockResolvedValue({});
    const mutateMock = vi.fn();
    vi.spyOn(queries, "useTriggerJudgeEval").mockReturnValue({
      mutateAsync: mutateAsyncMock,
      mutate: mutateMock,
      isPending: false,
    } as any);

    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <BenchmarkBriefsCard />
        </QueryClientProvider>
      </MemoryRouter>
    );

    const evalBtn = screen.getByRole("button", { name: /Evaluate Rubric/i });
    expect(evalBtn).toBeDefined();
    evalBtn.click();
    expect(mutateAsyncMock).toHaveBeenCalledWith({
      sessionId: "session-sneakers-1",
      force: false,
    });
  });

  it("does not render conflicting Run Failed badge when campaign completed successfully", () => {
    // Set localStorage with error state from an earlier failed batch attempt
    localStorage.setItem(
      "eval_benchmark_batch_states",
      JSON.stringify({
        "smart-water-bottle": {
          briefId: "smart-water-bottle",
          status: "error",
          sessionId: "session-smart-bottle-1",
        },
      })
    );

    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <BenchmarkBriefsCard />
        </QueryClientProvider>
      </MemoryRouter>
    );

    // Should only have Run Completed badge, not Run Failed
    expect(screen.getByText(/✓ Run Completed/i)).toBeDefined();
    expect(screen.queryByText(/⚠ Run Failed/i)).toBeNull();
  });
});
