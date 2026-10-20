import json
import symtable
from pathlib import Path

import pytest

from tests.helpers.fake_llm_stream import sse_client


def test_document_followup_does_not_shadow_tool_inventory():
    path = Path('routes/chat_routes.py')
    table = symtable.symtable(path.read_text(), str(path), 'exec')
    def descendants(scope):
        for child in scope.get_children():
            yield child
            yield from descendants(child)
    chat = next(child for child in descendants(table) if child.get_name() == 'chat_stream')
    assert chat.lookup('FAMILY_TOOLS').is_global()


@pytest.mark.asyncio
async def test_native_document_arguments_stream_before_save(monkeypatch):
    from src import clean_agent_preview as module
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.tool_policy import ToolPolicy
    from src.turn_contract import resolve_full_inventory_contract

    content = '<svg xmlns="http://www.w3.org/2000/svg"><text>AI</text></svg>'
    raw = json.dumps({'title': 'logo.svg', 'language': 'svg', 'content': content})
    saved = []
    deltas = [
        {'tool_calls': [{'index': 0, 'id': 'create-logo', 'function': {
            'name': 'create_document' if index == 0 else '', 'arguments': raw[index:index + 8]}}]}
        for index in range(0, len(raw), 8)
    ]
    rounds = [[{'choices': [{'delta': delta}]} for delta in deltas],
              {'choices': [{'delta': {'content': 'Created the logo.'}}]}]

    async def execute(block, **kwargs):
        saved.append(True)
        return 'create_document', {'doc_id': 'logo', 'title': 'logo.svg',
                                  'language': 'svg', 'content': content, 'version': 1}

    monkeypatch.setattr(module.httpx, 'AsyncClient', sse_client(rounds))
    monkeypatch.setattr(module, 'execute_tool_block', execute)
    schemas = [s for s in FUNCTION_TOOL_SCHEMAS if s['function']['name'] == 'create_document']
    contract = resolve_full_inventory_contract(schemas=schemas, policy=ToolPolicy())
    events = []
    async for chunk in module.stream_preview(
        endpoint_url='http://test', model='Ajax', headers={},
        messages=[{'role': 'user', 'content': 'Make an SVG logo'}],
        turn_contract=contract, session_id='svg-stream-test', owner='test',
        disabled_tools=set(), tool_policy=ToolPolicy(), max_rounds=3,
    ):
        if '[DONE]' in chunk: continue
        event = json.loads(chunk[6:])
        if event.get('type') in {'doc_stream_open', 'doc_stream_delta'}:
            assert not saved
        events.append(event)
    opens = [e for e in events if e.get('type') == 'doc_stream_open']
    deltas = [e['content'] for e in events if e.get('type') == 'doc_stream_delta']
    assert len(opens) == 1
    assert opens[0]['language'] == 'svg'
    assert len(deltas) > 1
    assert deltas[-1] == content
    assert any(e.get('type') == 'doc_update' for e in events)
