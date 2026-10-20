"""Provider endpoint normalization tests.

Covers ``normalize_base`` (strip whatever path the user pasted), and the
provider-root helpers ``_anthropic_api_root`` and ``_ollama_api_root``.
"""

from src import endpoint_resolver as er


# ── normalize_base: strip whatever path the user pasted ──

def test_normalize_base():
    for raw, expected in [
        ("https://api.openai.com/v1/chat/completions", "https://api.openai.com/v1"),
        ("https://api.openai.com/v1/completions", "https://api.openai.com/v1"),
        ("https://api.openai.com/v1/models/", "https://api.openai.com/v1"),
        ("https://api.anthropic.com/v1/messages", "https://api.anthropic.com"),
        ("http://localhost:11434/api/chat", "http://localhost:11434/api"),
        ("http://localhost:11434/api/tags", "http://localhost:11434/api"),
        ("http://localhost:11434/api/generate", "http://localhost:11434/api"),
        ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
        ("  https://api.openai.com/v1  ", "https://api.openai.com/v1"),
        ("", ""),
        (None, ""),
    ]:
        assert er.normalize_base(raw) == expected


def test_docker_saved_endpoint_is_loopback_on_native_runtime(monkeypatch):
    monkeypatch.setattr(er, "_running_in_container", lambda: False)
    assert er._rewrite_docker_host_for_native_runtime(
        "http://host.docker.internal:18059/v1"
    ) == "http://127.0.0.1:18059/v1"


def test_docker_saved_endpoint_stays_host_gateway_in_container(monkeypatch):
    monkeypatch.setattr(er, "_running_in_container", lambda: True)
    value = "http://host.docker.internal:18059/v1"
    assert er._rewrite_docker_host_for_native_runtime(value) == value


# ── provider-root helpers ──

def test_anthropic_api_root():
    for base, expected in [
        ("https://api.anthropic.com/v1", "https://api.anthropic.com"),
        ("https://api.anthropic.com", "https://api.anthropic.com"),
        # /v1 on a non-Anthropic host (OpenAI-compatible) must be preserved.
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
    ]:
        assert er._anthropic_api_root(base) == expected


def test_ollama_api_root():
    for base, expected in [
        ("https://ollama.com", "https://ollama.com/api"),
        ("http://localhost:11434/api", "http://localhost:11434/api"),
        # A non-Ollama host is returned untouched.
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
    ]:
        assert er._ollama_api_root(base) == expected
