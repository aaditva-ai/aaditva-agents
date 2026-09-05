import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AverageRubricCard } from "../AverageRubricCard";
import * as authedFetchModule from "../../../api/authedFetch";
import type { AverageEvaluationReport } from "../../../api/types";

const mockReport: AverageEvaluationReport = {
  userId: "user-123",
  totalRunCount: 3,
  evaluatedRunCount: 2,
  averageScore: 87.5,
  averageGrade: "Good",
  criteria: [
    { id: 1, name: "Multi-Agent Orchestration & Workflow", weight: 0.2, averageScore: 87.5 },
    { id: 2, name: "Quality Gate & Revision Loop", weight: 0.2, averageScore: 100 },
  ],
  generatedAt: "2026-09-01T12:00:00Z",
};

function renderWithClient(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <AverageRubricCard />
    </QueryClientProvider>
  );
}

describe("AverageRubricCard Component", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  afterEach(() => {
    queryClient.clear();
    vi.restoreAllMocks();
  });

  it("renders the average score, grade, and run counts once loaded", async () => {
    vi.spyOn(authedFetchModule, "authedFetch").mockResolvedValueOnce(mockReport);

    renderWithClient(queryClient);

    expect(screen.getByText(/Average Rubric Score Across All Runs/i)).toBeDefined();
    await waitFor(() => expect(screen.getByText(/87.5%/i)).toBeDefined());
    expect(screen.getByText(/Good/i)).toBeDefined();
    expect(screen.getByText(/2 evaluated campaign runs out of 3 total runs/i)).toBeDefined();
  });

  it("renders per-criterion average scores", async () => {
    vi.spyOn(authedFetchModule, "authedFetch").mockResolvedValueOnce(mockReport);

    renderWithClient(queryClient);

    await waitFor(() => expect(screen.getByText(/Multi-Agent Orchestration & Workflow/i)).toBeDefined());
    expect(screen.getByText(/Quality Gate & Revision Loop/i)).toBeDefined();
    expect(screen.getByText(/87.5 \/ 100/i)).toBeDefined();
    expect(screen.getByText(/100.0 \/ 100/i)).toBeDefined();
  });

  it("renders an empty state when the user has no evaluated runs yet", async () => {
    vi.spyOn(authedFetchModule, "authedFetch").mockResolvedValueOnce({
      userId: "user-456",
      totalRunCount: 1,
      evaluatedRunCount: 0,
      averageScore: 0,
      averageGrade: "Unsatisfactory",
      criteria: [],
      generatedAt: "2026-09-01T12:00:00Z",
    } satisfies AverageEvaluationReport);

    renderWithClient(queryClient);

    await waitFor(() =>
      expect(screen.getByText(/No evaluated campaign runs yet/i)).toBeDefined()
    );
  });
});
