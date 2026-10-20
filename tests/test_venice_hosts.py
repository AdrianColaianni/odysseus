"""Venice (https://api.venice.ai/api/v1) is an OpenAI-compatible cloud API with
native tool-calling, so the agent loop sends it native tool schemas."""
from src import agent_loop


def test_venice_host_gets_native_tools_for_an_unknown_model(monkeypatch):
    monkeypatch.setattr(agent_loop, "_route_endpoints", lambda db, url, owner: [])

    venice = agent_loop._agent_route_tool_mode("https://api.venice.ai/api/v1", "venice-uncensored")
    unknown = agent_loop._agent_route_tool_mode("https://example.invalid/v1", "venice-uncensored")

    assert venice[0] is True
    assert unknown[0] is False
