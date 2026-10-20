"""Regression coverage for structured-thinking model detection."""

from src.llm_core import _supports_thinking


def test_deepseek_v4_models_support_thinking():
    models = ["deepseek-v4", "DeepSeek-V4-Flash", "deepseek/deepseek-v4-flash"]
    assert [m for m in models if _supports_thinking(m) is not True] == []


def test_other_deepseek_models_are_not_promoted_to_thinking():
    for model in ("deepseek-v3", "deepseek-chat"):
        assert _supports_thinking(model) is False
