"""Regression tests for the tool-support heuristic in stream_agent_loop.

Verifies two critical cases:
  1. local Ollama endpoints must NOT enable native tool schemas by default
     (some models terminate after one token with schemas).
  2. api.deepseek.com must still be treated as tool-capable via the host
     allow-list (_API_HOSTS), so cloud deepseek users keep working.
"""
from types import SimpleNamespace

import pytest

import src.agent_loop as agent_loop
from src.agent_loop import (
    _agent_route_tool_mode,
    _endpoint_lookup_keys,
)


@pytest.fixture
def is_api_model(monkeypatch):
    """The route's native-tool decision, with the endpoint row's supports_tools stubbed."""
    def decide(model, endpoint_url, endpoint_supports=None):
        rows = [] if endpoint_supports is None else [SimpleNamespace(supports_tools=endpoint_supports)]
        monkeypatch.setattr(agent_loop, "_route_endpoints", lambda db, url, owner: rows)
        return _agent_route_tool_mode(endpoint_url, model)[0]
    return decide


def test_local_ollama_and_no_tool_models_default_to_fenced_tools(is_api_model):
    for model, url in [
        ("deepseek-r1:7b", "http://localhost:11434/v1"),  # Ollama returns HTTP 400 with schemas
        ("deepseek-r1:7b", "http://host.docker.internal:11434/v1"),
        ("qwen3.5:4b", "http://localhost:11434/v1"),
        ("qwen3.5:4b", "http://localhost:11434/api/chat"),
        ("gpt-oss-20b", "http://localhost:8000/v1"),
    ]:
        assert is_api_model(model, url) is False, (model, url)


def test_deepseek_cloud_api_gets_tools(is_api_model):
    for model in ("deepseek-chat", "deepseek-v3", "deepseek-r1"):
        assert is_api_model(model, "https://api.deepseek.com/v1") is (model != "deepseek-r1"), model


def test_endpoint_supports_flag_overrides_the_model_and_host_defaults(is_api_model):
    for model, url in [
        ("deepseek-r1:7b", "http://localhost:11434/v1"),
        ("qwen3.5:4b", "http://localhost:11434/api/chat"),
        ("gpt-oss-20b", "http://localhost:8000/v1"),
    ]:
        assert is_api_model(model, url, endpoint_supports=True) is True, (model, url)
    assert is_api_model("deepseek-chat", "https://api.deepseek.com/v1", endpoint_supports=False) is False


def test_tool_capable_models_on_local_non_ollama_servers_get_tools(is_api_model):
    for model in ("qwen2.5:14b", "qwen35-9b-ajax-tp2-67", "llama3.2:3b"):
        assert is_api_model(model, "http://localhost:8000/v1") is True, model


class TestEndpointLookupKeys:
    def test_chat_completions_url_matches_endpoint_base(self):
        keys = _endpoint_lookup_keys("http://localhost:11434/v1/chat/completions")

        assert "http://localhost:11434/v1" in keys
        assert "http://localhost:11434/v1/" in keys

    def test_native_ollama_chat_url_matches_api_base(self):
        keys = _endpoint_lookup_keys("http://host.docker.internal:11434/api/chat")

        assert "http://host.docker.internal:11434/api" in keys


def test_route_tool_mode_matches_credential_distinct_endpoint(monkeypatch):
    from core import database
    from src import endpoint_resolver

    rows = [
        SimpleNamespace(
            id="one",
            base_url="https://same.example/v1",
            api_key="key-one",
            provider_auth_id=None,
            supports_tools=True,
        ),
        SimpleNamespace(
            id="two",
            base_url="https://same.example/v1",
            api_key="key-two",
            provider_auth_id=None,
            supports_tools=False,
        ),
    ]

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return rows

    class Db:
        def query(self, *args, **kwargs):
            return Query()

        def close(self):
            return None

    monkeypatch.setattr(database, "SessionLocal", lambda: Db())
    monkeypatch.setattr(
        endpoint_resolver,
        "resolve_endpoint_runtime",
        lambda endpoint, owner=None: (endpoint.base_url, endpoint.api_key),
    )

    assert _agent_route_tool_mode(
        "https://same.example/v1",
        "custom-model",
        headers={"Authorization": "Bearer key-one"},
    )[0] is True
    assert _agent_route_tool_mode(
        "https://same.example/v1",
        "custom-model",
        headers={"Authorization": "Bearer key-two"},
    )[0] is False
