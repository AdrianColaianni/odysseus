"""Search providers degrade to [] on a non-JSON response body (issue #1129)."""

import json

import pytest

from services.search import providers


class _BadJSONResponse:
    """A 200 response whose body is not valid JSON (e.g. an HTML error page)."""
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        raise json.JSONDecodeError("Expecting value", "<html>down</html>", 0)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    # Keep everything offline + deterministic: no settings/DB, keys via env, and
    # both httpx verbs return a body that fails to decode.
    monkeypatch.setattr(providers, "_get_search_settings", lambda: {}, raising=False)
    monkeypatch.setattr(providers, "_safesearch_for", lambda *_a, **_k: None, raising=False)
    monkeypatch.setenv("DATA_BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setenv("SERPER_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_PSE_CX", "cx")
    monkeypatch.setattr(providers.httpx, "post", lambda *a, **k: _BadJSONResponse())
    monkeypatch.setattr(providers.httpx, "get", lambda *a, **k: _BadJSONResponse())


def test_every_keyed_provider_returns_empty_on_malformed_json():
    for search in (providers.brave_search, providers.google_pse_search,
                   providers.tavily_search, providers.serper_search):
        assert search("hello") == [], search.__name__
