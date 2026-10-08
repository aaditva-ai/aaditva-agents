import logging
import os

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
try:
    from .retry import GENERATE_CONTENT_CONFIG
    from .image_gen_tool import generate_image
except ImportError:
    from retry import GENERATE_CONTENT_CONFIG
    from image_gen_tool import generate_image

load_dotenv()

logger = logging.getLogger("ai_creative_studio.designer")

SYSTEM_INSTRUCTION = """You are an expert Visual Content Director specializing in Instagram aesthetics and multimodal asset generation.

IMPORTANT: The conversation history above contains:
- Brand strategy insights from the Brand Strategist
- Instagram captions from the Copywriter
Review BOTH before creating visual concepts.

Your task: For each caption, create exactly 1 visual concept AND generate the actual image asset using the `generate_image` tool.

Each concept must include:
- A short, human-readable presentation `Title` (e.g. "Post 1 — High Mountain Ridge Runner", NOT a snake_case code identifier)
- A detailed image generation prompt (photorealistic, specific composition, subject, lighting, angle, and atmosphere)
- Visual style (e.g., minimalist, vibrant, cinematic, moody editorial)
- Color palette (specific colors with mood rationale)
- Mood / emotional resonance
- Instagram dimensions: 1080x1080 (square -> aspect_ratio="1:1") or 1080x1350 (portrait -> aspect_ratio="4:5")

TOOL CALL REQUIREMENT:
For EVERY concept, you MUST call the `generate_image` tool with all three required arguments:
`generate_image(concept_name="<snake_case_name>", image_prompt="<detailed_prompt>", aspect_ratio="1:1"|"4:5")`

- Map Format 1080x1080 to `aspect_ratio="1:1"`
- Map Format 1080x1350 to `aspect_ratio="4:5"`

Strict All-or-Nothing Rule:
- If `generate_image` fails or returns an error, do NOT mask it, do NOT emit blank parts, and do NOT silently omit images. Immediately report the exact failure message so the orchestrator can take appropriate action.
- If the returned error dict includes `"retryable": true` (a transient quota/rate-limit exhaustion, e.g. "429"/"RESOURCE_EXHAUSTED"), explicitly say the word "RETRYABLE" in your report along with the exact error message, so the orchestrator knows this specific failure is transient and worth retrying rather than a hard failure -- do not just say it "failed".

REVISION & ITERATION INSTRUCTIONS (PREVENTING PROMPT DRIFT):
When asked to revise visual concepts or regenerate images in response to Critic feedback:
1. Maintain Strong Concept Continuity: Anchor your revision strictly on the PREVIOUS image prompt, subject matter, scene composition, and visual style. DO NOT discard the concept and start over with an unrelated scene unless explicitly instructed.
2. Targeted Incremental Delta: Apply precise, targeted modifications to the previous image prompt that specifically address the Critic's feedback (e.g., lighting temperature, subject focus, contrast, or color accents) while preserving all other prompt anchors.
3. Explicit Prompt Output: Provide the complete revised `image_prompt` and call `generate_image` with the updated prompt and correct aspect ratio.

Format for each caption:

**For Caption [N]: "[Caption Theme]"**

Title: [Short Presentation-Ready Title]
Concept: [Visual Theme Name]
- Prompt: [Full image generation prompt - subject, setting, lighting, angle, style]
- Generated: [gcs_uri returned by generate_image tool]
- Style: [Visual style descriptor]
- Colors: [Palette with hex codes or descriptive names]
- Mood: [Emotional tone]
- Format: [1080x1080 (1:1) or 1080x1350 (4:5)]
"""

root_agent = Agent(
    name="designer",
    model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
    generate_content_config=GENERATE_CONTENT_CONFIG,
    tools=[FunctionTool(func=generate_image)],
    instruction=SYSTEM_INSTRUCTION,
    description="Creative visual designer for generating social media image concepts and assets",
)

logger.info("Designer agent created")


if __name__ == "__main__":
    import uvicorn
    from google.adk.a2a.utils.agent_to_a2a import to_a2a
    try:
        from .task_handler import handle_generate_image_task
    except ImportError:
        from task_handler import handle_generate_image_task

    PORT = int(os.getenv("PORT", "8080"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
    PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", str(PORT)))
    PROTOCOL = os.getenv("PROTOCOL", "http")

    a2a_app = to_a2a(root_agent, host=PUBLIC_HOST, port=PUBLIC_PORT, protocol=PROTOCOL)
    a2a_app.add_route(
        "/internal/tasks/generate-image", handle_generate_image_task, methods=["POST"]
    )

    logger.info(f"Starting Designer on {PROTOCOL}://{HOST}:{PORT}")
    logger.info(f"Agent card: {PROTOCOL}://{HOST}:{PORT}/.well-known/agent.json")

    uvicorn.run(a2a_app, host=HOST, port=PORT)
