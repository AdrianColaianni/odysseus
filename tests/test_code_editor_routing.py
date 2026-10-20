
from src.turn_contract import requested_capabilities, selected_tools_for_request, standalone_code_request
from src.clean_agent_preview import compact_schemas
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


def test_standalone_code_targets_editor():
    for text in ('write snake in python code', 'Make an SVG of a circle', 'Generate an HTML webpage'):
        assert selected_tools_for_request(text) == {'create_document'}, text
        assert requested_capabilities(text) == {'documents'}, text


def test_other_work_does_not_become_new_code_document():
    for text in (
        'Write snake.py in my repository', 'Build a game in this workspace',
        'Make an SVG using Python', 'Explain this Python code',
        'Write an email about my game', 'Do not write any code',
        'Fix the code in this document',
    ):
        assert not standalone_code_request(text), text


def test_compact_editor_schema_retains_artifact_guidance():
    schema = next(s for s in compact_schemas(FUNCTION_TOOL_SCHEMAS, model='Ajax')
                  if s['function']['name'] == 'create_document')
    assert 'complete working implementation' in schema['function']['description']
    assert 'svg' in schema['function']['parameters']['properties']['language']['enum']


def test_format_only_creation_requires_resolved_document_authority():
    from src.clean_agent_preview import evaluate_preview_call
    args = {'title': 'Shape', 'language': 'svg', 'content': '<svg />'}
    assert evaluate_preview_call('create_document', args, 'just an svg',
        contract_required_tools={'create_document'}, turn_authorized_families={'documents'}).allowed
    assert not evaluate_preview_call('create_document', args, 'just an svg').allowed
