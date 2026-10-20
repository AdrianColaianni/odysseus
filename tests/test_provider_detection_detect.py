"""Provider detection tests — _detect_provider real hosts and false-positive rejection (re: #768).

These import the *real* helpers from ``src.llm_core`` (not local copies) so a
regression in hostname matching is actually caught. The point of the change
under test is that provider detection keys off the URL's *hostname*, not a
substring of the whole URL — so a domain appearing in a path/query, or a
look-alike host, must not be misclassified.
"""
from src import llm_core


def test_detect_provider_keys_off_the_real_host():
    for url, provider in [
        ("https://chatgpt.com/backend-api/codex/responses", "chatgpt-subscription"),
        ("https://api.anthropic.com", "anthropic"),
        # Groq's base carries an /openai/v1 path; detection must still see the host.
        ("https://api.groq.com/openai/v1", "groq"),
        ("https://api.example.com/v1", "openai"),
    ]:
        assert llm_core._detect_provider(url) == provider, url


def test_detect_provider_rejects_substring_false_positives():
    """The regression that motivated #768: substring matching mislabeled these."""
    for url in [
        "https://myproxy.internal/anthropic.com/v1",
        "https://example.com/v1?ref=anthropic.com",
        "https://anthropic.com.example/v1",
        None,
    ]:
        assert llm_core._detect_provider(url) == "openai", url
