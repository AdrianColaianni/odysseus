from src.clean_agent_preview import inline_suggestion_request


def test_ordinary_advice_does_not_require_open_document():
    for prompt in (
        'Suggest three names for a project.',
        'Review the pros and cons of postponing the meeting.',
    ):
        assert not inline_suggestion_request(prompt, require_editor_reference=True), prompt


def test_explicit_editor_review_still_requires_document():
    for prompt in ('Give suggestions to this document.', 'Provide inline comments.'):
        assert inline_suggestion_request(prompt, require_editor_reference=True), prompt


def test_visible_editor_can_still_accept_short_review_request():
    assert inline_suggestion_request('Proofread this.')
