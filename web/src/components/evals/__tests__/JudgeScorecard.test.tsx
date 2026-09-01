import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { JudgeScorecard } from "../JudgeScorecard";
import type { JudgeEvaluationResult } from "../../../api/types";

const mockEvaluationData: JudgeEvaluationResult = {
  sessionId: "test-eval-123",
  evaluatedAt: "2026-09-01T12:00:00Z",
  prompt: "Instagram campaign for a smart water bottle for health-conscious millennials",
  overallScore: 100.0,
  overallGrade: "Excellent",
  summary: "All 7 criteria achieved with highest distinction.",
  criteria: [
    {
      id: 1,
      name: "Multi-Agent Orchestration & Workflow",
      weight: 0.20,
      score: 100,
      rating: "Excellent",
      passed: true,
      rationale: "Clean pipeline sequence from Brand Strategist through PM.",
      evidence: ["Brand Strategist outputs passed to Copywriter and Designer"],
    },
    {
      id: 2,
      name: "Quality Gate & Revision Loop",
      weight: 0.20,
      score: 100,
      rating: "Excellent",
      passed: true,
      rationale: "Critic performed multimodal visual audit and formal approval.",
      evidence: ["Structured POSTS REVIEW and VISUALS REVIEW executed"],
    },
  ],
};

describe("JudgeScorecard Component", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  it("renders overall score, grade tier badge, and summary", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <JudgeScorecard initialData={mockEvaluationData} />
      </QueryClientProvider>
    );

    expect(screen.getByText(/LLM-as-a-Judge Rubric Scorecard/i)).toBeDefined();
    expect(screen.getAllByText(/100.0%/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/All 7 criteria achieved with highest distinction/i)).toBeDefined();
  });

  it("renders individual criterion items with weights and scores", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <JudgeScorecard initialData={mockEvaluationData} />
      </QueryClientProvider>
    );

    expect(screen.getByText(/Multi-Agent Orchestration & Workflow/i)).toBeDefined();
    expect(screen.getByText(/Quality Gate & Revision Loop/i)).toBeDefined();
    expect(screen.getAllByText(/Weight: 20%/i).length).toBe(2);
    expect(screen.getAllByText(/100 \/ 100/i).length).toBe(2);
  });
});
