from types import SimpleNamespace


from src.clean_agent_preview import active_editor_whole_draft_request


def test_targeted_email_edit_does_not_force_whole_body_replacement():
    for prompt in (
        'Change Tuesday to Wednesday only in my reply, not in the quoted email.',
        'Fix the spelling in this draft.',
        'Do not write another reply. Correct the date only.',
    ):
        document = SimpleNamespace(title='Fixture', language='email', current_content='Existing reply')
        assert not active_editor_whole_draft_request(document, prompt)


def test_composition_command_still_selects_whole_draft_writer():
    for prompt in (
        'Write reply this email',
        'Please respond to this email.',
        'Reply politely declining.',
    ):
        document = SimpleNamespace(title='Fixture', language='email', current_content='Existing reply')
        assert active_editor_whole_draft_request(document, prompt)
