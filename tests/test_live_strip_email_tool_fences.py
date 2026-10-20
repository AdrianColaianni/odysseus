"""Regression test for #3993: live chat left executed tool fences visible.

``EXEC_FENCE_RE`` in ``static/js/chatRenderer.js`` once came from a
hand-maintained subset of ``TOOL_TAGS``, so new tools left raw fences in the
live bubble until reload. It now builds from ``GET /api/tools``. The renderer
pulls browser globals and cannot be imported under node, so these guards pin
the shared source at the text level.
"""
import re
from pathlib import Path

_SRC = Path("static/js/chatRenderer.js")

# Legitimate code-example languages the renderer must leave visible.
_NON_STRIPPED = {"bash", "python"}


def test_frontend_keeps_no_hardcoded_tool_list():
    """Root-cause guard for #3993: chatRenderer.js must NOT reintroduce a
    hand-maintained tool list. A hard-coded mirror of TOOL_TAGS silently drifts
    when a new tool is added — leaving its executed fence in the live bubble
    until reload. The live regex must instead be built from the backend's
    authoritative set fetched at runtime."""
    source = _SRC.read_text(encoding="utf-8")
    assert "EXEC_TOOL_TAGS" not in source, (
        "chatRenderer.js reintroduced a hard-coded EXEC_TOOL_TAGS list; the "
        "live-strip tags must come from GET /api/tools so TOOL_TAGS stays the "
        "single source (#3993)."
    )
    assert "/api/tools" in source, (
        "chatRenderer.js must fetch the tool set from /api/tools to build "
        "EXEC_FENCE_RE."
    )
    assert "JSON.parse(content)" in source, (
        "chatRenderer.js must validate inline JSON before stripping same-line "
        "tool fences so Markdown metadata stays visible."
    )
    # The bash/python carve-out must survive the move to the runtime list.
    m = re.search(r"EXEC_FENCE_NON_TOOL\s*=\s*new Set\(\[(?P<body>.*?)\]\)", source, re.DOTALL)
    assert m, "bash/python carve-out (EXEC_FENCE_NON_TOOL) not found in chatRenderer.js"
    carve_out = set(re.findall(r"['\"]([a-z_]+)['\"]", m.group("body")))
    assert carve_out == _NON_STRIPPED, (
        f"EXEC_FENCE_NON_TOOL must carve out exactly {sorted(_NON_STRIPPED)}, "
        f"got {sorted(carve_out)}"
    )


def test_api_tools_endpoint_serves_full_tool_tags(monkeypatch):
    """The frontend's single source is GET /api/tools; a subset would silently
    shrink the live-strip list (#3993)."""
    from unittest.mock import MagicMock

    import routes.model_routes as model_routes
    from src.agent_tools import TOOL_TAGS
    from tests.helpers.routes import route_endpoint

    monkeypatch.setattr(model_routes, "_load_settings", lambda: {})
    list_tools = route_endpoint(model_routes.setup_model_routes(MagicMock()), "/api/tools", "GET")
    assert [tool["id"] for tool in list_tools()["tools"]] == sorted(TOOL_TAGS)
