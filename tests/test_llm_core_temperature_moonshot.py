"""Regression tests: Moonshot/Kimi temperature detection and payload behavior.

Moonshot kimi-k2.5+ models reject custom temperature values; the payload
builder must detect the Moonshot provider and omit temperature for the affected
model family. Self-hosted Kimi deployments (non-Moonshot URL) must keep the
caller-specified temperature unchanged.
"""
import httpx

from src import llm_core


def test_moonshot_k2_5_plus_uses_fixed_temperature():
    models = ["kimi-k2.5", "moonshot/kimi-k2.6", "kimi-k2.6-preview"]
    assert [m for m in models if not llm_core._moonshot_rejects_custom_temperature("moonshot", m)] == []


def test_other_models_keep_temperature():
    cases = [
        ("openai", "kimi-k2.6"),
        ("moonshot", "kimi-k2-thinking"),
        ("moonshot", "kimi-k2.50"),
        ("moonshot", None),
    ]
    assert [c for c in cases if llm_core._moonshot_rejects_custom_temperature(*c)] == []


def test_moonshot_provider_detection():
    for url in ("https://api.moonshot.ai/v1/chat/completions", "https://api.moonshot.cn/v1/chat/completions"):
        assert llm_core._detect_provider(url) == "moonshot"


def _capture_openai_payload(
    monkeypatch,
    model,
    temperature,
    url="https://api.openai.com/v1/chat/completions",
):
    """Run a synchronous OpenAI-compatible call and return the posted JSON body."""
    llm_core._response_cache.clear()
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None, verify=None):
        seen["json"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "OK"}}]},
        )

    monkeypatch.setattr(llm_core.httpx, "post", fake_post)
    result = llm_core.llm_call(
        url,
        model,
        [{"role": "user", "content": "Say OK"}],
        temperature=temperature,
        max_tokens=5,
    )
    assert result == "OK"
    return seen["json"]


def test_moonshot_k2_6_payload_omits_temperature(monkeypatch):
    payload = _capture_openai_payload(
        monkeypatch,
        "kimi-k2.6",
        0.7,
        url="https://api.moonshot.ai/v1/chat/completions",
    )
    assert "temperature" not in payload


def test_self_hosted_kimi_k2_6_payload_keeps_temperature(monkeypatch):
    payload = _capture_openai_payload(
        monkeypatch,
        "kimi-k2.6",
        0.7,
        url="http://localhost:8000/v1/chat/completions",
    )
    assert payload["temperature"] == 0.7
