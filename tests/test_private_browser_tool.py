"""Pure browser formatting/path and Wave 5B cleanup regressions.

Legacy successful page-command/batch/recovery tests have been superseded by
failed-before-dispatch resource tests in test_browser_resource_identity.py.
"""
import asyncio
import pytest
import json
from pathlib import Path

from src.agent_tools.web_tools import (
    YouTubeTool,
    shutdown_private_browser_sessions,
)
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


def test_generate_image_has_stable_native_schema() -> None:
    names = {
        schema.get("function", {}).get("name")
        for schema in FUNCTION_TOOL_SCHEMAS
    }

    assert "generate_image" in names


def test_all_native_array_schemas_declare_items() -> None:
    """Provider APIs reject an array schema without an item schema."""

    def walk(value, path="schema"):
        if isinstance(value, dict):
            if value.get("type") == "array":
                assert "items" in value, f"missing items at {path}"
            for key, child in value.items():
                yield from walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{path}[{index}]")

    # Consume the generator so assertions execute for every schema node.
    list(walk(FUNCTION_TOOL_SCHEMAS, "FUNCTION_TOOL_SCHEMAS"))


def test_youtube_tool_comments_falls_back_to_ytdlp(monkeypatch) -> None:
    from services.youtube import youtube_handler

    async def _fake_comments(video_id, max_comments=25, timeout=30):
        return {
            "success": True,
            "title": "Example Video",
            "channel": "Example Channel",
            "comments": [
                {"author": "Alice", "text": "Useful demo.", "likes": 12},
                {"author": "Bob", "text": "Loved the walkthrough.", "likes": 3},
            ],
        }

    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(youtube_handler, "fetch_youtube_comments", _fake_comments)

    result = asyncio.run(YouTubeTool().execute(
        json.dumps({
            "action": "comments",
            "url": "https://www.youtube.com/watch?v=abc123DEF45",
            "max_results": 2,
        }),
        {},
    ))

    assert result["exit_code"] == 0
    assert "Example Video" in result["output"]
    assert "@Alice [12 likes]: Useful demo." in result["output"]


def test_youtube_tool_latest_channel_parses_playlist_json() -> None:
    parsed = YouTubeTool._parse_ytdlp_json_output(json.dumps({
        "entries": [
            {"id": "vid123", "title": "Latest upload"},
            {"id": "vid122", "title": "Previous upload"},
        ]
    }))

    assert parsed["entries"][0]["title"] == "Latest upload"


def test_youtube_tool_latest_channel_parses_json_lines() -> None:
    parsed = YouTubeTool._parse_ytdlp_json_output(
        '{"id":"vid123","title":"Latest upload"}\n'
        '{"id":"vid122","title":"Previous upload"}\n'
    )

    assert [entry["id"] for entry in parsed["entries"]] == ["vid123", "vid122"]


def test_youtube_tool_latest_channel_formats_requested_upload_count(monkeypatch) -> None:
    async def _fake_ytdlp_json(self, url, *, timeout, flat_playlist=False, playlist_end=5):
        assert flat_playlist is True
        assert playlist_end == 5
        return {
            "success": True,
            "data": {
                "entries": [
                    {"id": f"vid{i}", "title": f"Upload {i}", "duration": 60 + i}
                    for i in range(1, 8)
                ]
            },
        }

    monkeypatch.setattr(YouTubeTool, "_ytdlp_json", _fake_ytdlp_json)

    result = asyncio.run(YouTubeTool().execute(
        json.dumps({
            "action": "latest_channel_video",
            "channel_url": "https://www.youtube.com/c/RAINBOLTGEO/videos",
            "max_results": 5,
        }),
        {},
    ))

    assert result["exit_code"] == 0
    assert "Latest 5 channel videos" in result["output"]
    assert "1. Upload 1" in result["output"]
    assert "5. Upload 5" in result["output"]
    assert "6. Upload 6" not in result["output"]


def test_youtube_tool_latest_channel_resolves_bad_handle(monkeypatch) -> None:
    calls = []

    async def _fake_ytdlp_json(self, url, *, timeout, flat_playlist=False, playlist_end=5):
        calls.append(url)
        if url == "https://www.youtube.com/@rainbolt/videos":
            return {"success": False, "error": "HTTP Error 404: Not Found"}
        if url.startswith("ytsearch10:"):
            return {
                "success": True,
                "data": {
                    "entries": [
                        {
                            "title": "rainbolt clips",
                            "channel": "rainbolt clips",
                            "uploader_id": "@rainboltshorts",
                            "channel_url": "https://www.youtube.com/channel/clips",
                            "view_count": 1000000,
                        },
                        {
                            "title": "geoguessr pro reacts",
                            "channel": "RAINBOLT",
                            "uploader_id": "@georainbolt",
                            "channel_url": "https://www.youtube.com/channel/official",
                            "view_count": 100,
                        },
                    ]
                },
            }
        if url == "https://www.youtube.com/channel/official/videos":
            return {
                "success": True,
                "data": {"entries": [{"id": "vid123", "title": "Official latest upload"}]},
            }
        return {"success": False, "error": f"unexpected url {url}"}

    monkeypatch.setattr(YouTubeTool, "_ytdlp_json", _fake_ytdlp_json)

    result = asyncio.run(YouTubeTool().execute(
        json.dumps({
            "action": "latest_channel_video",
            "handle": "@rainbolt",
            "max_results": 5,
        }),
        {},
    ))

    assert result["exit_code"] == 0
    assert "Official latest upload" in result["output"]
    assert calls == [
        "https://www.youtube.com/@rainbolt/videos",
        "ytsearch10:rainbolt official YouTube channel",
        "https://www.youtube.com/channel/official/videos",
    ]


def test_youtube_tool_channel_search_query_handles_urls_and_handles() -> None:
    assert YouTubeTool._channel_search_query("@rainbolt") == "rainbolt"
    assert YouTubeTool._channel_search_query("https://www.youtube.com/@rainbolt/videos") == "rainbolt"
    assert YouTubeTool._channel_search_query("https://www.youtube.com/c/RainboltGeo") == "RainboltGeo"


def test_youtube_tool_metadata_with_channel_url_returns_channel_uploads(monkeypatch) -> None:
    async def _fake_ytdlp_json(self, url, *, timeout, flat_playlist=False, playlist_end=5):
        assert flat_playlist is True
        return {
            "success": True,
            "data": {"entries": [{"id": "vid123", "title": "Latest upload"}]},
        }

    monkeypatch.setattr(YouTubeTool, "_ytdlp_json", _fake_ytdlp_json)

    result = asyncio.run(YouTubeTool().execute(
        json.dumps({
            "action": "metadata",
            "channel_url": "https://www.youtube.com/@example/videos",
            "max_results": 1,
        }),
        {},
    ))

    assert result["exit_code"] == 0
    assert "Latest channel video" in result["output"]
    assert "Latest upload" in result["output"]


def test_youtube_tool_comment_author_keeps_single_at_prefix() -> None:
    output = YouTubeTool()._format_comments(
        {
            "comments": [
                {"author": "@AlreadyPrefixed", "text": "Looks good.", "likes": 1}
            ]
        },
        "https://www.youtube.com/watch?v=abc123DEF45",
    )

    assert "@AlreadyPrefixed [1 likes]: Looks good." in output
    assert "@@AlreadyPrefixed" not in output


class _FakeBrowserMcp:
    def get_all_tools(self, disabled_map=None):
        disabled = (disabled_map or {}).get("builtin_browser", set())
        return [
            {
                "server_id": "builtin_browser",
                "server_name": "Built-in: Browser",
                "name": "browser_navigate",
                "qualified_name": "mcp__builtin_browser__browser_navigate",
                "description": "Navigate",
                "input_schema": {"type": "object", "properties": {}},
                "is_disabled": "browser_navigate" in disabled,
            }
        ]

    def get_all_openai_schemas(self, disabled_map=None):
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["qualified_name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in self.get_all_tools(disabled_map)
            if not tool["is_disabled"]
        ]

    def get_tool_descriptions_for_prompt(self, disabled_map=None, allowed_names=None):
        lines = []
        for tool in self.get_all_tools(disabled_map):
            if tool["is_disabled"]:
                continue
            if allowed_names is not None and tool["qualified_name"] not in allowed_names:
                continue
            lines.append(tool["qualified_name"])
        return "\n".join(lines)


def test_raw_browser_mcp_is_hidden_when_private_browser_is_available() -> None:
    from src.agent_loop import _build_system_prompt

    messages, schemas = _build_system_prompt(
        [{"role": "user", "content": "open https://example.com and take a screenshot"}],
        "gpt-5.5",
        None,
        _FakeBrowserMcp(),
        disabled_tools=set(),
        relevant_tools={
            "private_browser",
            "builtin_browser",
            "mcp__builtin_browser__browser_navigate",
        },
        compact=True,
    )

    prompt_text = "\n".join(str(message.get("content") or "") for message in messages)
    schema_names = {
        schema.get("function", {}).get("name")
        for schema in schemas
    }

    assert "mcp__builtin_browser__browser_navigate" not in prompt_text
    assert "mcp__builtin_browser__browser_navigate" not in schema_names


def test_generic_go_to_phrase_is_browser_interaction() -> None:
    from src.agent_loop import _looks_like_explicit_browser_interaction

    assert _looks_like_explicit_browser_interaction(
        "Go to Airbnb and find stays in Tokyo for next weekend under $150/night."
    )
    assert _looks_like_explicit_browser_interaction(
        "Navigate to the vendor portal and check the pricing table."
    )
    assert _looks_like_explicit_browser_interaction(
        "Open Spotify's web player and search for Bach cello suites."
    )
    assert not _looks_like_explicit_browser_interaction(
        "Find rules for getting rid of garbage in Setagaya-ku."
    )


@pytest.mark.asyncio
async def test_shutdown_cleans_up_invalidated_registered_browser_session(monkeypatch) -> None:
    """Shutdown cleanup must terminate owned daemons even if record.session was invalidated."""
    from unittest.mock import MagicMock
    from src import browser_identity as browser

    cleaned: list[tuple[Path, str]] = []
    def fake_force_cleanup(root, key, **kwargs):
        cleaned.append((Path(root), key))

    monkeypatch.setattr("src.browser_lifecycle.force_cleanup", fake_force_cleanup)

    record = MagicMock()
    record.key = "ody-test1234"
    record.env = {"AGENT_BROWSER_SOCKET_DIR": "/tmp/test-socket-dir"}
    record.session = None  # Simulates cancellation / invalidate()
    record.invalidate = MagicMock()

    monkeypatch.setattr(browser, "_REGISTRY", {("alice", "thread"): record})

    await shutdown_private_browser_sessions()

    assert cleaned == [(Path("/tmp/test-socket-dir"), "ody-test1234")]
    assert browser._REGISTRY == {}
    record.invalidate.assert_called_once()
