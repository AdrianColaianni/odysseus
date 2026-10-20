"""Provider detection tests — hostname matching helpers (re: #768).

These import the *real* helpers from ``src.llm_core`` (not local copies) so a
regression in hostname matching is actually caught. The point of the change
under test is that provider detection keys off the URL's *hostname*, not a
substring of the whole URL — so a domain appearing in a path/query, or a
look-alike host, must not be misclassified.
"""
from src import llm_core


def test_host_match_accepts_the_host_and_its_subdomains():
    assert llm_core._host_match("https://anthropic.com/v1", "anthropic.com")
    assert llm_core._host_match("https://api.anthropic.com/v1", "anthropic.com")
    assert llm_core._host_match("https://api.together.ai/v1", "together.xyz", "together.ai")
    # A fully-qualified host with a trailing dot is legal and resolvable.
    assert llm_core._host_match("https://api.anthropic.com./v1", "anthropic.com")


def test_host_match_rejects_the_domain_outside_the_host():
    for url in [
        "https://myproxy.internal/anthropic.com/v1",
        "https://example.com/v1?ref=anthropic.com",
        "https://anthropic.com.example/v1",
        None,
        "",
    ]:
        assert not llm_core._host_match(url, "anthropic.com"), url
