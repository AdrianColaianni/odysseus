"""Research is offered in compact chat, not automatically executed by keywords."""
import json
import pytest

from src.tool_policy import ToolPolicy
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
from src.turn_contract import resolve_turn_contract


@pytest.mark.asyncio
async def test_chat_dispatches_research_and_streams_only_confirmed_job_link(monkeypatch):
    import src.clean_agent_preview as preview
    for status in [200, 503]:
        monkeypatch.setenv('AUTH_ENABLED', 'false')
        posted = []
        responses = iter([
            {'tool_calls': [{'index': 0, 'id': 'research-call', 'function': {
                'name': 'trigger_research', 'arguments': '{"topic":"AI info","max_rounds":1}',
            }}]},
            {'content': 'Research is running.' if status == 200 else 'Research service is unavailable.'},
        ])

        class Response:
            status_code = status
            text = 'service unavailable'
            def json(self): return {'session_id': 'fixture-research-job'}
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def raise_for_status(self): pass
            async def aiter_lines(self):
                yield 'data: ' + json.dumps({'choices': [{'delta': next(responses)}]})
                yield 'data: [DONE]'

        class Client:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def stream(self, *args, **kwargs): return Response()
            async def post(self, url, **kwargs):
                posted.append((url, kwargs['json']))
                return Response()

        # Only HTTP boundaries are replaced: model transport + research service.
        # Tool conversion, policy, dispatcher and research implementation are real.
        monkeypatch.setattr(preview.httpx, 'AsyncClient', Client)
        raw = [chunk async for chunk in preview.stream_preview(
            endpoint_url='http://model.test', model='test', headers={},
            messages=[{'role': 'user', 'content': 'research ai info'}],
            turn_contract=resolve_turn_contract(
                capabilities={'research'}, schemas=FUNCTION_TOOL_SCHEMAS, policy=ToolPolicy()), session_id='fixture-chat', owner='fixture-owner',
            disabled_tools=set(), tool_policy=ToolPolicy(),
        )]
        events = [json.loads(chunk[6:]) for chunk in raw if '[DONE]' not in chunk]
        assert len(posted) == 1 and posted[0][0].endswith('/api/research/start')
        assert posted[0][1] == {'query': 'AI info', 'max_rounds': 1,
            'origin_chat_id': 'fixture-chat', 'max_time': 120}
        tool = next(e for e in events if e.get('type') == 'tool_output')
        assert tool['execution_attempted'] and not tool['blocked']
        assert tool['error'] == (status != 200)
        streamed = ''.join(e.get('delta', '') for e in events)
        notices = [e for e in events if e.get('type') == 'ui_control']
        if status == 200:
            assert notices[0]['data']['research_session_id'] == 'fixture-research-job'
            assert streamed.count('](#research-fixture-research-job)') == 1
        else:
            assert not notices and '#research-' not in streamed
        metrics = next(e['data'] for e in events if e.get('type') == 'metrics')
        assert metrics['clean_v3_turn'][-1]['content'] == streamed
