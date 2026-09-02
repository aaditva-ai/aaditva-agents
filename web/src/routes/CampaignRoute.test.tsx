import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { CampaignRoute } from "./CampaignRoute";
import * as queriesModule from "../api/queries";
import type { Transcript } from "../api/selectTranscript";

function renderWithProviders(ui: ReactNode, queryClient: QueryClient, initialPath = "/c/session-123") {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/c/:sessionId" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("CampaignRoute", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.restoreAllMocks();
  });

  it("shows loading indicator when campaign has just started and is still polling with 0 events", () => {
    const transcript: Transcript = {
      status: "starting",
      groups: [],
    };

    vi.spyOn(queriesModule, "useCampaignEvents").mockReturnValue({
      data: transcript,
      isLoading: false,
      isSuccess: true,
      isError: false,
      failureCount: 0,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
    } as unknown as ReturnType<typeof queriesModule.useCampaignEvents>);

    renderWithProviders(<CampaignRoute />, queryClient);

    expect(screen.getByText("Campaign started — waiting for first event…")).toBeDefined();
    expect(screen.getByTestId("polling-loading-indicator")).toBeDefined();
  });

  it("shows loading indicator when campaign is running and still polling with 0 events", () => {
    const transcript: Transcript = {
      status: "running",
      groups: [],
    };

    vi.spyOn(queriesModule, "useCampaignEvents").mockReturnValue({
      data: transcript,
      isLoading: false,
      isSuccess: true,
      isError: false,
      failureCount: 0,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
    } as unknown as ReturnType<typeof queriesModule.useCampaignEvents>);

    renderWithProviders(<CampaignRoute />, queryClient);

    expect(screen.getByText("Campaign started — waiting for first event…")).toBeDefined();
    expect(screen.getByTestId("polling-loading-indicator")).toBeDefined();
  });

  it("does not show polling loading indicator when campaign has reached terminal state with 0 events", () => {
    const transcript: Transcript = {
      status: "failed",
      groups: [],
    };

    vi.spyOn(queriesModule, "useCampaignEvents").mockReturnValue({
      data: transcript,
      isLoading: false,
      isSuccess: true,
      isError: false,
      failureCount: 0,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
    } as unknown as ReturnType<typeof queriesModule.useCampaignEvents>);

    renderWithProviders(<CampaignRoute />, queryClient);

    expect(screen.getByText("Campaign started — waiting for first event…")).toBeDefined();
    expect(screen.queryByTestId("polling-loading-indicator")).toBeNull();
  });

  it("renders transcript view when events exist", () => {
    const transcript: Transcript = {
      status: "running",
      groups: [
        {
          key: "group-1",
          author: "creative_director",
          invocationId: "inv-1",
          steps: [
            {
              id: "step-1",
              author: "creative_director",
              invocationId: "inv-1",
              kind: "text",
              text: "Building market strategy...",
              timestamp: "2026-09-01T15:43:00Z",
            },
          ],
        },
      ],
    };

    vi.spyOn(queriesModule, "useCampaignEvents").mockReturnValue({
      data: transcript,
      isLoading: false,
      isSuccess: true,
      isError: false,
      failureCount: 0,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
    } as unknown as ReturnType<typeof queriesModule.useCampaignEvents>);

    renderWithProviders(<CampaignRoute />, queryClient);

    expect(screen.getByText("Building market strategy...")).toBeDefined();
    expect(screen.queryByText("Campaign started — waiting for first event…")).toBeNull();
  });
});
