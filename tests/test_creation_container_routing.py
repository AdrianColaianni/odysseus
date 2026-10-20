import pytest

from src.turn_contract import requested_capabilities, selected_tools_for_request


def test_automation_content_is_not_an_immediate_search_or_mail_action():
    from src.turn_contract import broad_web_briefing_request
    from src.clean_agent_preview import requests_mutation, authorized_write_families

    for prompt in (
        'create a task that research ai news every day 8 pm',
        'Each morning summarize my unread emails.',
        'Make two tasks to check my email and research news every day.',
    ):
        assert selected_tools_for_request(prompt) == {'manage_tasks'}, prompt
        assert requested_capabilities(prompt) == {'tasks'}, prompt
        assert not broad_web_briefing_request(prompt), prompt
        assert requests_mutation(prompt), prompt
        assert 'tasks' in authorized_write_families(prompt), prompt


def test_checklist_content_does_not_authorize_automation():
    for prompt in (
        'create a todo, answer emails, write mom, whatsapp, pay bank',
        'Make a checklist for my tasks tomorrow',
    ):
        assert selected_tools_for_request(prompt) == {'manage_notes'}, prompt
        assert requested_capabilities(prompt) == {'notes'}, prompt


def test_described_or_quoted_cadence_is_not_scheduler_authority():
    from src.turn_contract import creation_container_tool

    for prompt in (
        'Explain why I should research battery technology every Monday.',
        'Translate to French: Every Monday research battery technology.',
        'Every Monday I research battery technology.',
        'Every Monday at 09:00 UTC add a calendar meeting.',
        'Make a note: Every Monday research battery technology.',
        'Research battery technology now.',
    ):
        assert creation_container_tool(prompt) is None, prompt


def test_task_creation_contract_keeps_required_scheduler_available():
    from src.tool_policy import ToolPolicy
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.turn_contract import resolve_turn_contract
    prompt = 'can you make a task to research latest news in ai every day 8 pm'
    selected = selected_tools_for_request(prompt)
    contract = resolve_turn_contract(
        capabilities=requested_capabilities(prompt), schemas=FUNCTION_TOOL_SCHEMAS,
        policy=ToolPolicy(), selected_tools=selected, required_tools=selected,
        message=prompt)
    assert not contract.unavailable
    assert 'manage_tasks' in contract.required
    assert 'web_search' not in contract.offered


@pytest.mark.asyncio
async def test_runtime_does_not_override_task_creation_with_search(monkeypatch):
    import json
    from dataclasses import replace
    import src.clean_agent_preview as runtime
    from src.tool_policy import ToolPolicy
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.turn_contract import resolve_full_inventory_contract

    requests = []
    replies = iter([
        {'tool_calls': [{'index': 0, 'id': 'task-1', 'function': {
            'name': 'manage_tasks', 'arguments': json.dumps({'action': 'create',
            'name': 'AI news', 'prompt': 'Research latest AI news',
            'schedule_type': 'daily', 'time': '20:00'})}}]},
        {'content': 'Daily AI news task created.'},
    ])

    class Response:
        def __init__(self, delta): self.delta = delta
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def aiter_lines(self):
            yield 'data: ' + json.dumps({'choices': [{'delta': self.delta}]})
            yield 'data: [DONE]'

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs):
            requests.append(kwargs['json'])
            return Response(next(replies))

    async def execute(block, **kwargs):
        assert block.tool_type == 'manage_tasks'
        return 'manage_tasks', {'exit_code': 0, 'response': 'Task created', 'task_id': 'fixture-task'}

    monkeypatch.setattr(runtime.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(runtime, 'execute_tool_block', execute)
    contract = replace(resolve_full_inventory_contract(
        schemas=[s for s in FUNCTION_TOOL_SCHEMAS if s['function']['name'] in {'manage_tasks', 'web_search'}],
        policy=ToolPolicy()), required=frozenset({'manage_tasks'}))
    _ = [chunk async for chunk in runtime.stream_preview(
        endpoint_url='http://test', model='Ajax', headers={}, turn_contract=contract,
        messages=[{'role': 'user', 'content': 'create task to do research once a day latest ai news'}],
        session_id='fixture', owner='fixture', disabled_tools=set(), tool_policy=ToolPolicy(), max_rounds=3)]
    assert requests[0]['tool_choice'] == 'auto'
    assert [s['function']['name'] for s in requests[0]['tools']] == ['manage_tasks']
