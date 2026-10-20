from src.clean_agent_preview import unbound_lookup_reference


def test_missing_subject_requires_context():
    for prompt in ('can u look it up', 'what about its price?'):
        history = [{'role': 'system', 'content': 'System'}, {'role': 'user', 'content': prompt}]
        assert unbound_lookup_reference(prompt, history)
        assert not unbound_lookup_reference(prompt, history, supplied_context=True)
        prior = [{'role': 'user', 'content': 'I am considering a Firefox phone.'}, {'role': 'assistant', 'content': 'Which features matter?'}]
        assert not unbound_lookup_reference(prompt, prior + history)


def test_explicit_subjects_and_other_intents_keep_normal_routing():
    for prompt in ('Find the Python documentation', 'What about its price compared to a Pixel 9?', 'Search for this https://example.org', 'helo'):
        assert not unbound_lookup_reference(prompt, [{'role': 'user', 'content': prompt}])
