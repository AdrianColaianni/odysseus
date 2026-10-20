from copy import deepcopy

from src.clean_agent_preview import compact_schemas, provider_compatible_tool_choice_request
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


def test_ajax_auto_decoding_preserves_selected_tool_boundary():
    tools = [s for s in FUNCTION_TOOL_SCHEMAS if s['function']['name'] in {'manage_tasks', 'manage_notes'}]
    for model in ['Ajax', 'local/Ajax']:
        for choice in ['required', {'type': 'function', 'function': {'name': 'manage_tasks'}}]:
            request = {'tools': tools, 'tool_choice': choice}
            original = deepcopy(request)
            compatible = provider_compatible_tool_choice_request(request, model)
            assert compatible['tool_choice'] == 'auto'
            names = {s['function']['name'] for s in compatible['tools']}
            assert names == ({'manage_tasks'} if isinstance(choice, dict) else {'manage_tasks', 'manage_notes'})
            assert request == original


def test_ajax_explicit_no_tools_is_preserved():
    request = {'tool_choice': 'none', 'tools': []}
    assert provider_compatible_tool_choice_request(request, 'Ajax') is request


def test_ajax_does_not_offer_ask_user():
    tools = [s for s in FUNCTION_TOOL_SCHEMAS
             if s['function']['name'] in {'ask_user', 'web_fetch'}]
    assert any(s['function']['name'] == 'ask_user' for s in tools)
    for model in ['Ajax', 'ajax_c375', 'local/Ajax']:
        names = {s['function']['name'] for s in compact_schemas(tools, model=model)}
        assert names == {'web_fetch'}, model


def test_other_models_keep_ask_user():
    tools = [s for s in FUNCTION_TOOL_SCHEMAS if s['function']['name'] == 'ask_user']
    for model in [None, 'not-ajax']:
        assert [s['function']['name'] for s in compact_schemas(tools, model=model)] == ['ask_user']
