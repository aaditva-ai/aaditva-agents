import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StepCard } from "./StepCard";
import type { StepGroup } from "../api/selectTranscript";

describe("StepCard markdown rendering", () => {
  it("renders bold markdown text with <strong> tag", () => {
    const group: StepGroup = {
      key: "group-1",
      author: "creative_director",
      invocationId: "inv-1",
      steps: [
        {
          id: "step-1",
          author: "creative_director",
          invocationId: "inv-1",
          kind: "text",
          text: "1. **Brand Strategist** will research the market.\n2. **Copywriter** will create posts.",
          timestamp: "2026-09-01T15:43:00Z",
        },
      ],
    };

    render(<StepCard group={group} />);

    // Check that strong elements exist with the expected text
    const strongBrand = screen.getByText("Brand Strategist");
    expect(strongBrand.tagName).toBe("STRONG");

    const strongCopywriter = screen.getByText("Copywriter");
    expect(strongCopywriter.tagName).toBe("STRONG");
  });

  it("renders headers, lists, code, and links in markdown", () => {
    const group: StepGroup = {
      key: "group-2",
      author: "creative_director",
      invocationId: "inv-2",
      steps: [
        {
          id: "step-2",
          author: "creative_director",
          invocationId: "inv-2",
          kind: "text",
          text: "### Step 1: Market Research\n\n- Key trend: `Agentic Systems`\n- Read [Documentation](https://example.com)",
          timestamp: "2026-09-01T15:43:00Z",
        },
      ],
    };

    render(<StepCard group={group} />);

    const header = screen.getByRole("heading", { level: 3 });
    expect(header).toBeDefined();
    expect(header.textContent).toBe("Step 1: Market Research");

    const code = screen.getByText("Agentic Systems");
    expect(code.tagName).toBe("CODE");

    const link = screen.getByRole("link", { name: "Documentation" });
    expect(link.getAttribute("href")).toBe("https://example.com");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("handles non-text step kinds like tool_call, tool_result, image, and transfer", () => {
    const group: StepGroup = {
      key: "group-3",
      author: "creative_director",
      invocationId: "inv-3",
      steps: [
        {
          id: "step-tc",
          author: "creative_director",
          invocationId: "inv-3",
          kind: "tool_call",
          toolName: "brand_strategist",
          timestamp: "2026-09-01T15:43:00Z",
        },
        {
          id: "step-tr",
          author: "creative_director",
          invocationId: "inv-3",
          kind: "tool_result",
          toolName: "brand_strategist",
          text: '{"result": "ok"}',
          timestamp: "2026-09-01T15:43:00Z",
        },
        {
          id: "step-img",
          author: "creative_director",
          invocationId: "inv-3",
          kind: "image",
          imageUrl: "https://example.com/asset.png",
          text: "Visual campaign post 1",
          timestamp: "2026-09-01T15:43:00Z",
        },
        {
          id: "step-tf",
          author: "creative_director",
          invocationId: "inv-3",
          kind: "transfer",
          timestamp: "2026-09-01T15:43:00Z",
        },
      ],
    };

    render(<StepCard group={group} />);

    expect(screen.getByLabelText("Tool call: brand_strategist")).toBeDefined();
    expect(screen.getByLabelText("Tool result for brand_strategist")).toBeDefined();
    const img = screen.getByAltText("Generated campaign asset: Visual campaign post 1") as HTMLImageElement;
    expect(img).toBeDefined();
    expect(img.src).toBe("https://example.com/asset.png");
    expect(screen.getByText("Visual campaign post 1")).toBeDefined();
    expect(screen.getByLabelText("Agent handoff transfer")).toBeDefined();
  });

  it("renders inline image whenever imageUrl is provided on any step kind", () => {
    const group: StepGroup = {
      key: "group-4",
      author: "creative_director",
      invocationId: "inv-4",
      steps: [
        {
          id: "step-tc-img",
          author: "creative_director",
          invocationId: "inv-4",
          kind: "tool_call",
          toolName: "display_image",
          imageUrl: "https://signed.example.com/inline-call.png",
          text: "Inline Call Asset",
          timestamp: "2026-09-01T15:43:00Z",
        },
        {
          id: "step-text-img",
          author: "creative_director",
          invocationId: "inv-4",
          kind: "text",
          text: "Here is the poster:",
          imageUrl: "https://signed.example.com/inline-text.png",
          timestamp: "2026-09-01T15:43:00Z",
        },
      ],
    };

    render(<StepCard group={group} />);

    const callImg = screen.getByAltText("Generated campaign asset: Inline Call Asset") as HTMLImageElement;
    expect(callImg).toBeDefined();
    expect(callImg.src).toBe("https://signed.example.com/inline-call.png");

    const textImg = screen.getByAltText("Generated campaign asset: Here is the poster:") as HTMLImageElement;
    expect(textImg).toBeDefined();
    expect(textImg.src).toBe("https://signed.example.com/inline-text.png");
  });
});
