"""Token-parameter selection for provider setup (REAL src.llm_core).

Split from `test_provider_classification.py` to keep the token-param quirk
separate from provider identification and error formatting.

  * `_uses_max_completion_tokens` — the gpt-5 / o-series quirk that the probe
    and chat payload builders branch on.

conftest.py stubs the heavy deps (sqlalchemy, src.database), so importing the
real module is side-effect free.
"""

from src.llm_core import _uses_max_completion_tokens


# ── _uses_max_completion_tokens ──
# gpt-5 / o-series need `max_completion_tokens`; everything else `max_tokens`.

class TestUsesMaxCompletionTokens:
    def test_requires_max_completion_tokens(self):
        for model in [
            "gpt-5", "gpt-5.2", "gpt-5-mini", "o1", "o1-preview", "o3", "o3-mini",
            "o4-mini", "gpt-4.5", "gpt-4.5-preview", "openrouter/openai/o3",
        ]:
            assert _uses_max_completion_tokens(model) is True

    def test_uses_plain_max_tokens(self):
        for model in [
            # gpt-4o must NOT be confused with the o-series ("o4"/"o1" tokens).
            "gpt-4o", "gpt-4o-mini", "gpt-4.1", "claude-opus-4", "llama-3.3-70b",
            "deepseek-chat", "", None,
        ]:
            assert _uses_max_completion_tokens(model) is False
