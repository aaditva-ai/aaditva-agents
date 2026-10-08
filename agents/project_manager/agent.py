import datetime
import json
import logging
import os

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

try:
    from .retry import GENERATE_CONTENT_CONFIG
    from .notion_image_tool import attach_campaign_images
except ImportError:
    from retry import GENERATE_CONTENT_CONFIG
    from notion_image_tool import attach_campaign_images

load_dotenv()

logger = logging.getLogger("ai_creative_studio.project_manager")


def handle_notion_error(
    tool: BaseTool,
    args: dict,
    tool_context: ToolContext,
    tool_response: dict,
) -> dict | None:
    """Intercept Notion API errors and replace the raw stack trace with a clean message."""
    if not tool.name.startswith("API-"):
        return None

    content = (tool_response.get("content") or [{}])[0].get("text", "")
    try:
        data = json.loads(content)
    except Exception:
        return None

    status = data.get("status")
    if status not in (400, 404):
        return None

    message = data.get("message", "")
    code = data.get("code", "")
    logger.warning("Notion %s (%s) on %s — injecting recovery hint", status, code, tool.name)

    if status == 404 and code == "object_not_found":
        # The misleading Notion message blames sharing/permissions, but the real
        # cause is passing a database ID as page_id in the parent object.
        message = (
            "object_not_found: you passed a database ID as page_id. "
            'Use {"parent": {"database_id": "<id>"}} not {"parent": {"page_id": "<id>"}}.'
        )

    return {
        "content": [{
            "type": "text",
            "text": f"Notion {status} ({code}) on {tool.name}: {message}\n\nRetry with corrected parameters.",
        }]
    }


def get_system_instruction(project_database_id=None, tasks_database_id=None):
    notion_section = (
        f"""
Projects database ID: {project_database_id}
Tasks database ID: {tasks_database_id}

Also persist the project and tasks to these Notion databases using the available Notion tools.
Notion tools follow the pattern `API-<operation>` — use their exact names as listed in the tool
manifest. Use them directly — never wrap in `print()` or prefix with `default_api.`

Before creating anything, use the available tools to discover the schema of each database.
Only use property names and types that actually exist in the schema you discover.

Property rules:
- Always set the database parent using `database_id` — never `page_id`
- Never set "people" or "person" type properties — integration tokens cannot assign users; skip them
- For "relation" type properties linking tasks to the project: set ONLY {{"relation": [{{"id": "<project-page-id>"}}]}}.
  Never set sub-fields like name, state, start, lat on the relation - those are read-only rollups.
  If a task creation fails with a validation_error on a relation property, immediately retry
  creating that task WITHOUT the relation property entirely.
- Only set properties whose type you can identify from the schema response; if a property type
  is unclear after reading the schema, skip it and note it in the Notion Status

Image Embedding Rules:
- If campaign images are provided (under "Generated Images" with title, gcs_uri, and url):
  1. Capture the newly created project page ID (e.g. `project_page_id`).
  2. Call `attach_campaign_images(page_id=project_page_id, images=images_list)` ONCE with all image dictionaries.
  3. NEVER paste raw signed URLs or expiring links into the Notion page body text or bulleted lists.
  4. Report the outcome in the **Notion Status** section (e.g. "Project created, 8 tasks linked, 3 images embedded directly into project page").

If any Notion call fails, continue — the text timeline is always the primary deliverable.
Write your complete response AFTER all Notion operations are done (or have failed).
"""
        if project_database_id
        else ""
    )

    return f"""You are a Project Manager specializing in creative campaign execution.

    Today's date is {datetime.date.today().strftime("%B %d, %Y")}.
    Use this as the starting point for all timelines.

    Your goal: create a complete project plan for the campaign.
    {notion_section}
    **Project Timeline:**
    Phase 1: Strategy & Research | [date] → [date] | [key activities]
    Phase 2: Content Creation    | [date] → [date] | [key activities]
    Phase 3: Review & Revision   | [date] → [date] | [key activities]
    Phase 4: Launch & Monitoring | [date] → [date] | [key activities]

    **Task List:**
    | Task | Owner | Deadline | Status |
    [list each task with realistic deadlines from today; set Owner to TBD]

    **Budget Breakdown:**
    [by category with approximate allocations]

    **Milestones:**
    [3-5 key checkpoints with dates]

    **Notion Status:**
    [What happened - e.g. "Project created (ID: xxx), 8 tasks linked, 3 visual assets embedded" or "Notion not configured - text timeline only"]
    """


def create_project_manager_agent():
    """Create the Project Manager agent, with Notion MCP if credentials are set."""
    notion_token = os.getenv("NOTION_TOKEN")
    notion_project_db_id = os.getenv("NOTION_PROJECT_DATABASE_ID")
    notion_tasks_db_id = os.getenv("NOTION_TASKS_DATABASE_ID")

    if not notion_token or not notion_project_db_id or not notion_tasks_db_id:
        logger.warning("Notion credentials not set — running without Notion integration")

        return Agent(
            name="project_manager",
            model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            generate_content_config=GENERATE_CONTENT_CONFIG,
            instruction=get_system_instruction(),
            description="Project manager that creates campaign timelines and task breakdowns",
        )

    else:
        logger.info(
            f"Notion configured — projects database: {notion_project_db_id}, tasks database: {notion_tasks_db_id}"
        )

        from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
        from mcp import StdioServerParameters

        server_params = StdioServerParameters(
            command="notion-mcp-server",
            env={
                "NOTION_TOKEN": notion_token,
                "PATH": os.environ.get("PATH", ""),
            },
        )
        notion_toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=server_params,
                timeout=30.0,
            )
        )

        return Agent(
            name="project_manager",
            model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            generate_content_config=GENERATE_CONTENT_CONFIG,
            after_tool_callback=handle_notion_error,
            instruction=get_system_instruction(
                project_database_id=notion_project_db_id,
                tasks_database_id=notion_tasks_db_id,
            ),
            description="Project manager with Notion integration for task tracking and asset embedding",
            tools=[notion_toolset, FunctionTool(func=attach_campaign_images)],
        )


root_agent = create_project_manager_agent()
logger.info("Project Manager agent created")


if __name__ == "__main__":
    import uvicorn
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    PORT = int(os.getenv("PORT", "8080"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
    PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", str(PORT)))
    PROTOCOL = os.getenv("PROTOCOL", "http")

    a2a_app = to_a2a(root_agent, host=PUBLIC_HOST, port=PUBLIC_PORT, protocol=PROTOCOL)

    logger.info(f"Starting Project Manager on {PROTOCOL}://{HOST}:{PORT}")
    logger.info(f"Agent card: {PROTOCOL}://{HOST}:{PORT}/.well-known/agent.json")

    uvicorn.run(a2a_app, host=HOST, port=PORT)
