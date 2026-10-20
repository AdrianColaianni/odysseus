from src.turn_contract import requested_capabilities
from src.clean_agent_preview import requests_mutation


def test_temporal_rescheduling_is_calendar_action():
    for prompt in [
        'Push that event back by two hours.',
        'Could you postpone my appointment until Friday?',
        'Shift the meeting to 16:00 UTC.',
    ]:
        assert requested_capabilities(prompt) == {'calendar'}, prompt
        assert requests_mutation(prompt), prompt


def test_temporal_discussion_does_not_authorize_calendar_write():
    from src.turn_contract import calendar_retiming_request
    for prompt in [
        'Do not push that event back by two hours.',
        'Why did they postpone my appointment until Friday?',
        'Explain how to bring the meeting forward by 30 minutes.',
        'The event was delayed by one day.',
        'Push the code to the remote repository.',
    ]:
        assert not calendar_retiming_request(prompt), prompt
