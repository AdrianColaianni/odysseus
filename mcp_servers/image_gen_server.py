"""MCP server exposing image generation through src.ai_interaction.do_generate_image."""

import asyncio
import json
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

server = Server("image_gen")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="generate_image",
            description="Generate an image using an image-capable model (e.g. gpt-image-1)",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Image description prompt"},
                    "model": {"type": "string", "description": "Model name (auto-detects if omitted)"},
                    "size": {"type": "string", "description": "Image size (default 1024x1024)"},
                    "quality": {"type": "string", "description": "Quality: low, medium, high, auto (default medium)"},
                },
                "required": ["prompt"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "generate_image":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    from src.ai_interaction import do_generate_image
    from src.settings import get_setting

    owner = str(arguments.get("_odysseus_owner") or "").strip() or None
    request = {key: arguments[key] for key in ("prompt", "model", "size", "quality") if arguments.get(key)}
    result = await do_generate_image(json.dumps(request), owner=owner)
    if result.get("error"):
        return [TextContent(type="text", text=f"Error: {result['error']}")]

    image_url = result["image_url"]
    if image_url.startswith("/"):
        # A fully qualified link stays clickable when the model echoes it.
        image_url = (get_setting("app_public_url", "") or "").rstrip("/") + image_url
    # "Direct link:" rather than an "image_url:" label: small models copied the
    # label token into the link href.
    text = (
        f"{result['results']}\n"
        f"Direct link: {image_url}\n"
        f"model: {result['image_model']}\nsize: {result['image_size']}"
    )
    return [TextContent(type="text", text=text)]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
