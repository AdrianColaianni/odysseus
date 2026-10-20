"""Regression: api_call reaches the model for API-integration intent (#3794).

The repro prompt matched no domain in ``_classify_agent_request``, so it was
treated as low-signal and ``api_call`` was never advertised to the model.
"""
import pytest

agent_loop = pytest.importorskip("src.agent_loop")

REPRO = "Use the api_call tool to call Home Assistant GET /api/states"


def test_integration_prompts_are_not_low_signal():
    for prompt in [REPRO, "check my home assistant lights", "call my gitea integration to list repos"]:
        intent = agent_loop._classify_agent_request([], prompt)
        assert intent["low_signal"] is False, (prompt, intent)
        assert "integrations" in intent["domains"], (prompt, intent)


def test_integrations_domain_offers_the_api_call_schema():
    assert "api_call" in agent_loop._DOMAIN_TOOL_MAP["integrations"]
    schema_names = {s.get("function", {}).get("name") for s in agent_loop.FUNCTION_TOOL_SCHEMAS}
    assert "api_call" in schema_names


def test_integrations_domain_has_a_rule_pack():
    # _domain_rules_for_tools indexes _DOMAIN_RULES[domain] directly, so a domain
    # present in _DOMAIN_TOOL_MAP without a _DOMAIN_RULES entry would KeyError the
    # moment api_call is selected.
    rules = agent_loop._domain_rules_for_tools({"api_call"})
    assert any("api_call" in r for r in rules), rules


def test_plain_greeting_does_not_pull_api_call():
    intent = agent_loop._classify_agent_request([], "hey there, how are you")
    assert "integrations" not in intent["domains"], intent
