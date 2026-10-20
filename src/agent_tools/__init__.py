"""Agent tool registry: TOOL_HANDLERS plus the names importers take from this package."""

from src.tool_utils import _truncate, get_mcp_manager, set_mcp_manager  # noqa: F401
from src.tool_types import TOOL_TAGS, ToolBlock  # noqa: F401

from .subprocess_tools import BashTool, HostShellTool, PythonTool
from .web_tools import WebSearchTool, WebFetchTool, PdfExtractTool, PrivateBrowserTool, YouTubeTool
from .weather_tools import WeatherTool
from .media_tools import ExtractTextTool, InspectMediaTool, TranscribeMediaTool
from .filesystem_tools import ReadFileTool, WriteFileTool, EditFileTool, ApplyPatchTool, LsTool, GlobTool, GrepTool, GetWorkspaceTool
from .coding_tools import TodoWriteTool
from .document_tools import CreateDocumentTool, UpdateDocumentTool, EditDocumentTool, SuggestDocumentTool, ManageDocumentTool
from .interaction_tools import AskUserTool, UpdatePlanTool
from .model_interaction_tools import chat_with_model, ask_teacher, list_models
from .bg_job_tools import ManageBgJobsTool
from .session_tools import create_session, list_sessions, send_to_session, manage_session
from .admin_tools import ADMIN_TOOL_HANDLERS


def _session_adapter(fn):
    """Wrap a fn(content, session_id, owner=) impl as a registry execute(content, ctx)."""
    async def _execute(content: str, ctx: dict) -> dict:
        return await fn(content, ctx.get("session_id"), owner=ctx.get("owner"))
    return _execute


TOOL_HANDLERS = {
    "bash": BashTool().execute,
    "host_shell": HostShellTool().execute,
    "python": PythonTool().execute,
    "web_search": WebSearchTool().execute,
    "get_weather": WeatherTool().execute,
    "web_fetch": WebFetchTool().execute,
    "pdf_extract": PdfExtractTool().execute,
    "youtube_tool": YouTubeTool().execute,
    "private_browser": PrivateBrowserTool().execute,
    "inspect_media": InspectMediaTool().execute,
    "extract_text": ExtractTextTool().execute,
    "transcribe_media": TranscribeMediaTool().execute,
    "read_file": ReadFileTool().execute,
    "write_file": WriteFileTool().execute,
    "edit_file": EditFileTool().execute,
    "apply_patch": ApplyPatchTool().execute,
    "todowrite": TodoWriteTool().execute,
    "ls": LsTool().execute,
    "glob": GlobTool().execute,
    "grep": GrepTool().execute,
    "create_document": CreateDocumentTool().execute,
    "update_document": UpdateDocumentTool().execute,
    "edit_document": EditDocumentTool().execute,
    "suggest_document": SuggestDocumentTool().execute,
    "manage_documents": ManageDocumentTool().execute,
    "get_workspace": GetWorkspaceTool().execute,
    "ask_user": AskUserTool().execute,
    "update_plan": UpdatePlanTool().execute,
    "chat_with_model": _session_adapter(chat_with_model),
    "ask_teacher": _session_adapter(ask_teacher),
    "list_models": _session_adapter(list_models),
    "manage_bg_jobs": ManageBgJobsTool().execute,
    "create_session": _session_adapter(create_session),
    "list_sessions": _session_adapter(list_sessions),
    "send_to_session": _session_adapter(send_to_session),
    "manage_session": _session_adapter(manage_session),
}
# Config/integration admin tools (manage_endpoints/mcp/webhooks/tokens/settings).
TOOL_HANDLERS.update(ADMIN_TOOL_HANDLERS)

# Keep an agent turn bounded by default. Callers can still opt into a higher
# limit explicitly, but a stale/repeating tool loop must not consume a whole
# session before the user gets control back.
MAX_AGENT_ROUNDS = 20

from src.tool_parsing import parse_tool_blocks, strip_tool_blocks  # noqa: E402, F401
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, function_call_to_tool_block  # noqa: E402, F401
from src.tool_execution import execute_tool_block, format_tool_result  # noqa: E402, F401
from .document_tools import set_active_document, set_active_model  # noqa: E402, F401
