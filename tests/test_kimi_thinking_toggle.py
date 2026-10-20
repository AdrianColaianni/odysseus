from src.model_profiles import supports_user_thinking_toggle
from src.llm_core import _apply_hosted_thinking_mode


def test_kimi_toggle_matches_hosted_request():
    for model in ('moonshotai/kimi-k3', 'kimi-k2.5'):
        assert supports_user_thinking_toggle(model)
        for mode, expected in (('on', 'enabled'), ('off', 'disabled')):
            payload = {}
            _apply_hosted_thinking_mode(payload, 'moonshot', model, mode)
            assert payload['thinking']['type'] == expected, (model, mode)


def test_older_kimi_is_not_assumed_switchable():
    assert not supports_user_thinking_toggle('kimi-k2-thinking')
