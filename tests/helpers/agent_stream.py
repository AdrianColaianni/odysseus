"""Drain and parse the SSE chunks that `stream_agent_loop` yields.

For tests that drive the real agent loop with a fake provider. Not for
`stream_preview`, whose fake sits at the httpx layer (see `fake_llm_stream`).
"""
import asyncio
import json


def collect_chunks(gen):
    """Run an async generator to completion and return its chunks."""
    async def _drain():
        return [chunk async for chunk in gen]

    return asyncio.run(_drain())


def sse_events(chunks):
    """Parse each `data: {...}` chunk, skipping `[DONE]` and non-JSON lines."""
    events = []
    for chunk in chunks:
        if not chunk.startswith("data: ") or chunk.startswith("data: [DONE]"):
            continue
        try:
            events.append(json.loads(chunk[6:]))
        except json.JSONDecodeError:
            pass
    return events


def delta_chunk(text):
    """One provider SSE chunk carrying a text delta."""
    return "data: " + json.dumps({"delta": text}) + "\n\n"


def patch_agent_loop_basics(monkeypatch, agent_loop=None):
    """Stub the settings, MCP and token-count lookups the loop makes each round.

    Keeps the real loop body and tool parsing. Tests that also need the
    executor, the provider stream or the approval gate patch those themselves.
    """
    if agent_loop is None:
        import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
