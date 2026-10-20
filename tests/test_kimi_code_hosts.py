"""Kimi Code host-allowlist behavior (follow-up to provider support).

Kimi Code (https://api.kimi.com/coding/v1) is a subscription, OpenAI-compatible
cloud API with native tool-calling. These tests pin the host-list integration:
  - agent loop sends native tool schemas to Kimi Code (not fenced-block parsing).
"""
from src import agent_loop


class TestAgentToolHosts:
    def test_kimi_code_in_api_hosts(self):
        assert "api.kimi.com" in agent_loop._API_HOSTS

    def test_kimi_code_url_matches_api_host(self):
        url = "https://api.kimi.com/coding/v1/chat/completions"
        assert any(h in url for h in agent_loop._API_HOSTS)

    def test_unknown_host_not_matched(self):
        url = "https://example.invalid/v1/chat/completions"
        assert not any(h in url for h in agent_loop._API_HOSTS)

