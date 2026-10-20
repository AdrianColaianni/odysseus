"""Regression: shell verbs must not promote informational chat to agent mode.

The shell-verb pattern used to be a bare word match
(`\\b(deploy|build|...|rm)\\b\\s+\\S+`), so any sentence merely containing one
of these common English words escalated a plain chat turn to agent mode via
routes/chat_routes.py. That broke the module's stated contract ("only promote
plain chat to agent mode when the user asks the assistant to take an action,
not when the user asks how a feature works"). The pattern is now anchored to
imperative position (start of message, optionally after "please") or to a
"can/could/would/will you ..." request.
"""
from src.action_intents import classify_tool_intent


def test_informational_shell_questions_stay_plain_chat():
    assert not classify_tool_intent("What does the grep command do?").needs_tools
    assert not classify_tool_intent("How do I tail a log file in production?").needs_tools
    assert not classify_tool_intent("Is it safe to kill a process with kill -9?").needs_tools


def test_incidental_shell_words_stay_plain_chat():
    assert not classify_tool_intent("My cat ate my homework").needs_tools
    assert not classify_tool_intent("The movie was a real kill joy for everyone").needs_tools


def test_imperative_shell_commands_still_promote_to_agent():
    assert classify_tool_intent("tail the nginx error log").needs_tools
    assert classify_tool_intent("restart the media server").needs_tools
    assert classify_tool_intent("please install docker on the host").needs_tools
    assert classify_tool_intent("cat /etc/hosts").needs_tools


def test_can_you_shell_requests_still_promote_to_agent():
    assert classify_tool_intent("can you grep the logs for 500 errors").needs_tools
    assert classify_tool_intent("could you tail the access log").needs_tools
