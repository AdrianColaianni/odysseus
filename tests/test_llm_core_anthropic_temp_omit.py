"""Regression guard: Opus 4.7+ rejects the temperature field entirely.

Anthropic removed the sampling parameters (temperature, top_p, top_k) starting
with Claude Opus 4.7 — sending `temperature` at all, even 0.0, returns HTTP 400.
This broke every native-Anthropic call to Opus 4.7/4.8, including the research
endpoint probe (temperature=0) and all DeepResearcher LLM calls, because
_build_anthropic_payload sent `temperature` unconditionally.

Earlier Claude models (Opus 4.6 and below, every Sonnet/Haiku) still accept
temperature in [0.0, 1.0], so the omission is version-gated — the clamp-to-[0,1]
behavior for those models (test_llm_core_anthropic_temp_clamp.py) is unchanged.
"""
from src.llm_core import _anthropic_rejects_temperature, _build_anthropic_payload


def test_opus_47_plus_rejects_temperature():
    models = [
        "claude-opus-4-7",
        "claude-opus-4-8-20260101",  # dated snapshot suffix
        "anthropic/claude-opus-4-7",  # provider-prefixed id
        "claude-opus-4-10",  # future minor still >= 4.7
        # A missing minor reads as `.0` (issue #5753): before the fix these fell
        # through to "accepts temperature" and every call 400'd.
        "claude-opus-5",
        "claude-opus-5-20260101",
    ]
    assert [m for m in models if _anthropic_rejects_temperature(m) is not True] == []


def test_older_claude_models_keep_temperature():
    models = [
        "claude-opus-4-6",
        "claude-opus-4",
        "claude-opus-4-20250514",  # Opus 4.0 dated id: the date must NOT read as a 4.7+ minor
        "claude-opus-4-1-20250805",
        "claude-sonnet-4-6",
        # The date directly after "opus-" must not parse as major version 20240229.
        "claude-3-opus-20240229",
        "octopus-4-8",  # "opus" only as a substring of another word
        "",
        None,
        123,
        ["claude-opus-4-8"],
    ]
    assert [m for m in models if _anthropic_rejects_temperature(m) is not False] == []


def _payload(model, temperature=0.0):
    return _build_anthropic_payload(
        model, [{"role": "user", "content": "hi"}], temperature, 100
    )


def test_payload_omits_temperature_for_opus_47_plus():
    # The endpoint probe sends temperature=0; on Opus 4.7+ that field must be gone.
    payload = _payload("claude-opus-4-8", 0.0)
    assert "temperature" not in payload


def test_payload_keeps_temperature_for_older_models():
    payload = _payload("claude-opus-4-6", 0.3)
    assert payload["temperature"] == 0.3
    # Older models retain the [0,1] clamp (Nietzsche preset at 1.2 -> 1.0).
    assert _payload("claude-3-5-sonnet", 1.2)["temperature"] == 1.0

