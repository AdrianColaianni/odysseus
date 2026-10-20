"""Provider endpoint model-selection tests.

Covers ``_first_chat_model``: auto-picking the first usable chat model from a
provider's model list, skipping embedding/tts/image models when possible.
"""

from src import endpoint_resolver as er


# ── _first_chat_model: never auto-pick an embedding/tts/etc. model ──

def test_first_chat_model_skips_non_chat():
    models = ["text-embedding-ada-002", "whisper-1", "gpt-4o", "dall-e-3"]
    assert er._first_chat_model(models) == "gpt-4o"


def test_first_chat_model_falls_back_to_first_when_all_non_chat():
    models = ["text-embedding-3-large", "text-embedding-3-small"]
    assert er._first_chat_model(models) == "text-embedding-3-large"


def test_first_chat_model_empty():
    for models in [[], None]:
        assert er._first_chat_model(models) is None
