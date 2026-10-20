import asyncio
import json

from src.agent_tools.web_tools import PrivateBrowserTool


def test_screenshot_cannot_overwrite_nonimage_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr("src.tool_execution.get_active_workspace", lambda: str(tmp_path))

    async def forbidden(*args, **kwargs):
        raise AssertionError("browser must not launch with nonimage destination")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    for name in ["output.html", "source.svg", "report.pdf", "notes.txt"]:
        source = tmp_path / name
        source.write_bytes(b"original artifact")
        result = asyncio.run(PrivateBrowserTool().execute(
            json.dumps({"action": "screenshot", "path": "/workspace/" + name}),
            {"session_id": "artifact-safety"},
        ))
        assert result["exit_code"] == 1, name
        assert result["failure_kind"] == "browser_page_authority_unavailable"
        assert result["executed"] is False
        assert source.read_bytes() == b"original artifact"
