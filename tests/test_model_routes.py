"""Tests for model route helper functions — pure logic, no server needed."""
import asyncio
import json
import sys
import threading
import time
import types
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from tests.helpers.import_state import clear_fake_endpoint_resolver_modules, preserve_import_state

with preserve_import_state("core.database", "src.database", "core.session_manager", "routes.model_routes"):
    # Other tests stub this module during collection. These helper tests need
    # the real URL normalization helpers so Anthropic /v1 handling is covered.
    clear_fake_endpoint_resolver_modules()

    import routes.model_routes as model_routes
    import src.database as src_database
    import src.endpoint_resolver as endpoint_resolver
    import src.llm_core as llm_core
    from routes.model_routes import (
        _match_provider_curated,
        _curate_models,
        _visible_models,
        _normalize_model_ids,
        _api_key_fingerprint,
        _is_chat_model,
        _classify_endpoint,
        _effective_endpoint_kind,
        _probe_endpoint,
        _ping_endpoint,
        _parse_model_list,
        _normalize_refresh_mode,
        _normalize_endpoint_refresh_mode,
        _endpoint_refresh_mode,
        _is_google_api_base,
        _speech_settings_using_endpoint,
        _clear_speech_settings_for_endpoint,
        _endpoint_settings_using_endpoint,
        _clear_endpoint_settings_for_endpoint,
        _clear_user_pref_endpoint_refs,
        _default_endpoint_needs_assignment,
        _PROVIDER_CURATED,
    )
    from src.llm_core import ANTHROPIC_MODELS


# ── speech endpoint settings ──

def test_speech_endpoint_dependents_include_stt():
    settings = {"stt_provider": "endpoint:voice"}
    assert _speech_settings_using_endpoint(settings, "voice") == ["Speech to Text"]


def test_clear_speech_endpoint_settings_resets_tts_and_stt():
    settings = {
        "tts_provider": "endpoint:voice",
        "tts_model": "custom-tts",
        "stt_provider": "endpoint:voice",
        "stt_model": "custom-stt",
    }

    assert _clear_speech_settings_for_endpoint(settings, "voice") == [
        "Text to Speech",
        "Speech to Text",
    ]
    assert settings == {
        "tts_provider": "disabled",
        "tts_model": "tts-1",
        "stt_provider": "disabled",
        "stt_model": "base",
    }


def test_endpoint_cleanup_preserves_legacy_default_fallback_data():
    settings = {
        "default_endpoint_id": "dead",
        "default_model": "primary",
        "default_model_fallbacks": [
            {"endpoint_id": "dead", "model": "fallback-a"},
            {"endpoint_id": "keep", "model": "fallback-b"},
        ],
        "foreground_model_fallbacks": [
            {"endpoint_id": "dead", "model": "foreground"},
        ],
        "utility_model_fallbacks": [{"endpoint_id": "dead", "model": "utility"}],
        "vision_model_fallbacks": [{"endpoint_id": "dead", "model": "vision"}],
        "stt_provider": "endpoint:dead",
        "stt_model": "whisper",
    }

    assert _endpoint_settings_using_endpoint(settings, "dead", include_speech=True) == [
        "Default Model",
        "Foreground Model Fallbacks",
        "Utility Model Fallbacks",
        "Vision Model Fallbacks",
        "Speech to Text",
    ]
    assert _clear_endpoint_settings_for_endpoint(settings, "dead", include_speech=True) == [
        "Default Model",
        "Foreground Model Fallbacks",
        "Utility Model Fallbacks",
        "Vision Model Fallbacks",
        "Speech to Text",
    ]
    assert settings["default_endpoint_id"] == ""
    assert settings["default_model"] == ""
    assert settings["default_model_fallbacks"] == [
        {"endpoint_id": "dead", "model": "fallback-a"},
        {"endpoint_id": "keep", "model": "fallback-b"},
    ]
    assert settings["foreground_model_fallbacks"] == []
    assert settings["utility_model_fallbacks"] == []
    assert settings["vision_model_fallbacks"] == []
    assert settings["stt_provider"] == "disabled"
    assert settings["stt_model"] == "base"


def test_endpoint_cleanup_updates_active_scoped_prefs_but_preserves_legacy_data():
    scoped = {
        "foreground_model_fallbacks": [
            {"endpoint_id": "dead", "model": "ownerless"},
        ],
        "default_model_fallbacks": [
            {"endpoint_id": "dead", "model": "legacy-ownerless"},
        ],
        "_users": {
            "alice": {
                "utility_endpoint_id": "dead",
                "utility_model": "utility",
                "foreground_model_fallbacks": [
                    {"endpoint_id": "dead", "model": "foreground"},
                ],
                "vision_model_fallbacks": [{"endpoint_id": "dead", "model": "vision"}],
            },
            "bob": {
                "default_endpoint_id": "keep",
                "default_model": "chat",
            },
        },
    }
    assert _clear_user_pref_endpoint_refs(scoped, "dead") == 2
    assert scoped["foreground_model_fallbacks"] == []
    assert scoped["default_model_fallbacks"] == [
        {"endpoint_id": "dead", "model": "legacy-ownerless"},
    ]
    assert scoped["_users"]["alice"] == {
        "utility_endpoint_id": "",
        "utility_model": "",
        "foreground_model_fallbacks": [],
        "vision_model_fallbacks": [],
    }
    assert scoped["_users"]["bob"]["default_endpoint_id"] == "keep"

    legacy = {
        "default_model_fallbacks": [{"endpoint_id": "dead", "model": "chat"}],
    }
    assert _clear_user_pref_endpoint_refs(legacy, "dead") == 0
    assert legacy["default_model_fallbacks"] == [
        {"endpoint_id": "dead", "model": "chat"}
    ]


# ── _default_endpoint_needs_assignment (add-endpoint auto-default) ──

def test_default_assignment_follows_enabled_state():
    assert _default_endpoint_needs_assignment("", {"a", "b"}) is True
    # #3586: a default pointing at a disabled endpoint left Memory -> Tidy
    # failing with "No default model configured"; adding an endpoint reassigns it.
    assert _default_endpoint_needs_assignment("disabled-ep", {"new-ep"}) is True
    assert _default_endpoint_needs_assignment("live-ep", {"live-ep", "new-ep"}) is False


# ── _match_provider_curated ──

def test_match_provider_curated_prefers_url_over_provider():
    for url, provider, expected in (
        ("https://z.ai/v1", "openai", "zai"),
        ("https://api.deepseek.com/v1", "openai", "deepseek"),
        ("https://api.groq.com/openai/v1", "openai", "groq"),
        ("https://api.mistral.ai/v1", "openai", "mistral"),
        ("https://api.together.xyz/v1", "openai", "together"),
        ("https://api.fireworks.ai/inference/v1", "openai", "fireworks"),
        ("https://generativelanguage.googleapis.com/v1beta", "openai", "google"),
        ("https://api.x.ai/v1", "openai", "xai"),
        ("https://ollama.com/api", "openai", "ollama"),
        ("https://api.kimi.com/coding/v1", "openai", "kimi-code"),
        ("https://localhost:1234", "openai", "openai"),
        ("https://localhost:1234", None, None),
        (None, "openai", "openai"),
        # #2230: the Z.AI coding plan has its own list, even with no provider.
        ("https://z.ai/api/coding", "openai", "zai-coding"),
        ("https://z.ai/api/coding/", "openai", "zai-coding"),
        ("https://z.ai/api/coding", None, "zai-coding"),
    ):
        assert _match_provider_curated(url, provider) == expected, url


# ── _probe_endpoint: Z.AI coding plan (#2230) ──

def _probe_urls_as_given(monkeypatch):
    monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
    monkeypatch.setattr(model_routes, "_normalize_base", lambda url: url.rstrip("/"))


class TestProbeZaiCoding:
    """Regression coverage for the Z.AI coding endpoint probing path."""

    def test_probe_keeps_server_models_and_appends_curated(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            return httpx.Response(200, json={"data": [{"id": "glm-5.1"}, {"id": "custom-finetune"}]},
                                 request=httpx.Request("GET", url))

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)
        result = _probe_endpoint("https://z.ai/api/coding", "key")
        assert "glm-5.1" in result
        assert "custom-finetune" in result
        coding_curated = _PROVIDER_CURATED.get("zai-coding", [])
        appended = [m for m in coding_curated if m in result and m != "glm-5.1"]
        assert len(appended) > 0, "curated-only models should be appended"

    def test_probe_does_not_use_base_zai_curated(self, monkeypatch):
        """The coding endpoint must use zai-coding, NOT the base zai list."""
        _probe_urls_as_given(monkeypatch)

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            return httpx.Response(200, json={"data": [{"id": "glm-5.1"}]},
                                 request=httpx.Request("GET", url))

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)
        result = _probe_endpoint("https://z.ai/api/coding", "key")
        base_only = set(_PROVIDER_CURATED.get("zai", [])) - set(_PROVIDER_CURATED.get("zai-coding", []))
        for model in base_only:
            assert model not in result, f"base-zai-only model {model} should not appear for coding endpoint"


# ── _curate_models ──

class TestCurateModels:
    def test_known_provider_partitions(self):
        models = ["gpt-4o", "gpt-4o-mini", "ft:gpt-4o:custom", "some-random-model"]
        curated, extra = _curate_models(models, "openai")
        assert "gpt-4o" in curated
        assert "gpt-4o-mini" in curated
        assert "some-random-model" in extra

    def test_unknown_provider_returns_all_as_curated(self):
        models = ["model-a", "model-b"]
        curated, extra = _curate_models(models, "unknown_provider")
        assert curated == models
        assert extra == []

    def test_curated_sorted_by_priority(self):
        models = ["gpt-4o-mini", "gpt-4o", "o3"]
        curated, _ = _curate_models(models, "openai")
        # gpt-4o should come before gpt-4o-mini in the curated list priority
        gpt4o_idx = curated.index("gpt-4o")
        gpt4o_mini_idx = curated.index("gpt-4o-mini")
        assert gpt4o_idx < gpt4o_mini_idx

    def test_provider_lists_partition_current_models(self):
        for provider, models, expected_extra in (
            ("deepseek", ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"], ["deepseek-coder"]),
            ("xai", ["grok-4", "grok-3-fast", "grok-2"], ["grok-2"]),
            ("xai", ["grok-4.3", "grok-4.3-fast"], []),
            ("groq", ["openai/gpt-oss-120b", "groq/compound", "llama-3.1-8b-instant",
                      "llama-4-scout-17b-16e-instruct"], []),
            ("google", ["gemini-3.5-flash", "gemini-3.1-pro"], []),
            ("kimi-code", ["kimi-for-coding", "other-model"], ["other-model"]),
        ):
            curated, extra = _curate_models(models, provider)
            assert curated == [m for m in models if m not in expected_extra], provider
            assert extra == expected_extra, provider


# ── _is_chat_model ──

def test_is_chat_model_excludes_media_audio_and_legacy_instruct_models():
    for model_id in (
        "gpt-4o", "gpt-4o-mini", "claude-sonnet-4", "llama-3.3-70b",
        "deepseek-chat", "gemini-2.0-flash", "o3",
        "llama-4-scout-17b-16e-instruct",
        "gemma-2b-it", "google/gemma-2b-it",
        "bigcode/starcoder2-15b-instruct",
        "gpt-4o-audio-preview",
    ):
        assert _is_chat_model(model_id) is True, model_id
    for model_id in (
        "dall-e-3", "tts-1", "whisper-1", "text-embedding-3-small",
        "gpt-image-1", "sora-1", "gpt-4o-realtime-preview", "gpt-audio",
        "gpt-3.5-turbo-instruct",
    ):
        assert _is_chat_model(model_id) is False, model_id
    # A non-compliant upstream can send a non-string id; it must not crash.
    for bad in (None, 123, 4.5, ["x"], {"a": 1}):
        assert _is_chat_model(bad) is True, bad


# ── _classify_endpoint ──

class TestClassifyEndpoint:
    def test_classify_uses_private_host_unless_kind_is_explicit(self):
        for url, kind, expected in (
            ("http://localhost:1234", None, "local"),
            ("http://127.0.0.1:8080/v1", None, "local"),
            ("http://192.168.1.100:5000", None, "local"),
            ("http://10.0.0.5:8000", None, "local"),
            ("http://100.117.136.97:34521/v1", None, "local"),
            ("https://10.example-cloud.com/v1", None, "api"),
            ("https://172.16.example-cloud.com/v1", None, "api"),
            ("https://192.168.example-cloud.com/v1", None, "api"),
            ("https://api.openai.com/v1", None, "api"),
            ("https://openrouter.ai/api/v1", None, "api"),
            ("", None, "api"),
            ("not-a-url", None, "api"),
            ("http://100.117.136.97:34521/v1", "proxy", "api"),
            ("http://100.117.136.97:34521/v1", "api", "api"),
            ("https://api.openai.com/v1", "local", "local"),
        ):
            args = (url,) if kind is None else (url, kind)
            assert _classify_endpoint(*args) == expected, (url, kind)

    def test_keyed_legacy_v1_endpoint_is_effective_proxy(self):
        ep = SimpleNamespace(endpoint_kind="auto", api_key="fake-key")
        assert _effective_endpoint_kind(ep, "http://100.117.136.97:34521/v1") == "proxy"

    def test_proxy_refresh_mode_defaults_manual(self):
        assert _normalize_refresh_mode("", "proxy") == "manual"
        assert _normalize_refresh_mode("auto", "proxy") == "manual"
        assert _normalize_refresh_mode("manual", "proxy") == "manual"
        assert _normalize_refresh_mode("auto", "api") == "auto"

    def test_google_refresh_mode_defaults_manual_unless_explicit(self):
        base = "https://generativelanguage.googleapis.com/v1beta/openai"
        assert _normalize_endpoint_refresh_mode("", "api", base) == "manual"
        assert _normalize_endpoint_refresh_mode(None, "auto", base) == "manual"
        assert _normalize_endpoint_refresh_mode("auto", "api", base) == "auto"

    def test_only_gemini_native_host_uses_google_models_api(self):
        assert _is_google_api_base("https://generativelanguage.googleapis.com/v1beta/openai") is True
        assert _is_google_api_base(
            "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1/endpoints/openapi"
        ) is False

    def test_existing_google_endpoint_refresh_mode_defaults_manual(self):
        ep = SimpleNamespace(
            model_refresh_mode=None,
            endpoint_kind="api",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        )
        assert _endpoint_refresh_mode(ep, "api") == "manual"
        ep.model_refresh_mode = "auto"
        assert _endpoint_refresh_mode(ep, "api") == "auto"

    def test_parse_model_list_accepts_json_and_text(self):
        assert _parse_model_list('["a", "b", "a"]') == ["a", "b"]
        assert _parse_model_list("a, b\nc") == ["a", "b", "c"]

    def test_ping_endpoint_does_not_request_models_for_openai_style_proxy(self, monkeypatch):
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        seen = []

        def fake_head(*args, **kwargs):
            raise AssertionError("generic proxy health check should not use HEAD")

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            seen.append(("GET", url))
            request = httpx.Request("GET", url)
            return httpx.Response(200, request=request)

        monkeypatch.setattr(model_routes.httpx, "head", fake_head)
        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        result = _ping_endpoint("http://100.117.136.97:34521/v1", "fake-key", timeout=1)

        assert result["reachable"] is True
        assert result["status_code"] == 200
        assert seen == [("GET", "http://100.117.136.97:34521/v1")]
        assert all(not url.endswith("/models") for _, url in seen)

    def test_ping_endpoint_falls_back_to_models_on_404(self, monkeypatch):
        """llama-swap returns 404 on /v1 but 200 on /v1/models."""
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        seen = []

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            seen.append(url)
            request = httpx.Request("GET", url)
            if url.endswith("/models"):
                return httpx.Response(200, request=request)
            return httpx.Response(404, request=request)

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        result = _ping_endpoint("http://172.17.0.1:8081/v1", timeout=1)

        assert result["reachable"] is True
        assert result["status_code"] == 200
        assert seen == [
            "http://172.17.0.1:8081/v1",
            "http://172.17.0.1:8081/v1/models",
        ]

    def test_ping_endpoint_no_models_fallback_on_auth_failure(self, monkeypatch):
        """401/403 are definitive — don't probe /models."""
        monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda url: url, raising=False)
        seen = []

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            seen.append(url)
            request = httpx.Request("GET", url)
            return httpx.Response(401, request=request)

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        result = _ping_endpoint("http://10.0.0.1:8080/v1", "bad-key", timeout=1)

        assert result["reachable"] is False
        assert result["status_code"] == 401
        # Should NOT have tried /models — 401 is definitive
        assert len(seen) == 1


# ── setup probing ──

class TestSetupProbeSafety:
    def test_keyed_probe_does_not_fallback_to_curated_on_auth_failure(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            request = httpx.Request("GET", url)
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.groq.com/openai/v1", "bad-key") == []

    def test_unkeyed_probe_can_still_use_curated_fallback(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.groq.com/openai/v1") == _PROVIDER_CURATED["groq"]

    def test_google_probe_uses_native_paginated_models_api(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)
        seen = []

        def fake_get(url, headers=None, params=None, timeout=None, verify=None, **kwargs):
            seen.append((url, headers, params, timeout, verify))
            request = httpx.Request("GET", url)
            page_token = (params or {}).get("pageToken")
            if page_token:
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "models": [{
                            "name": "models/gemini-page-two",
                            "supportedGenerationMethods": ["generateContent"],
                        }]
                    },
                )
            return httpx.Response(
                200,
                request=request,
                json={
                    "models": [
                        {
                            "name": "models/gemini-page-one",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "baseModelId": "gemini-base-id",
                            "name": "models/ignored-version",
                            "supportedGenerationMethods": ["generateText"],
                        },
                        {
                            "name": "models/imagen-4.0-generate-001",
                            "supportedGenerationMethods": ["predict"],
                        },
                        {
                            "name": "models/text-embedding-example",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                        {"name": "models/missing-method-metadata"},
                    ],
                    "nextPageToken": "next-page",
                },
            )

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://generativelanguage.googleapis.com/v1beta/openai", "google-key") == [
            "gemini-page-one",
            "gemini-base-id",
            "gemini-page-two",
        ]
        assert [call[0] for call in seen] == [
            "https://generativelanguage.googleapis.com/v1beta/models",
            "https://generativelanguage.googleapis.com/v1beta/models",
        ]
        assert seen[0][1] == {"Accept": "application/json", "x-goog-api-key": "google-key"}
        assert seen[0][2] == {"pageSize": 1000}
        assert seen[1][1] == {"Accept": "application/json", "x-goog-api-key": "google-key"}
        assert seen[1][2] == {"pageSize": 1000, "pageToken": "next-page"}

    def test_google_probe_does_not_use_curated_fallback_on_failure(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)

        def fake_get(url, headers=None, params=None, timeout=None, verify=None, **kwargs):
            request = httpx.Request("GET", url)
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://generativelanguage.googleapis.com/v1beta/openai", "bad-key") == []

    def test_keyed_anthropic_probe_does_not_fallback_on_failure(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.anthropic.com/v1", "bad-key") == []

    def test_anthropic_probe_does_not_double_v1(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)
        seen = []

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            seen.append(url)
            request = httpx.Request("GET", url)
            response = httpx.Response(
                200,
                request=request,
                json={"data": [{"id": "claude-sonnet-4-5"}]},
            )
            return response

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.anthropic.com/v1", "good-key") == ["claude-sonnet-4-5"]
        assert seen == ["https://api.anthropic.com/v1/models"]

    def test_ollama_cloud_probe_uses_native_tags_endpoint(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)
        seen = []

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            seen.append((url, headers))
            request = httpx.Request("GET", url)
            response = httpx.Response(
                200,
                request=request,
                json={"models": [{"name": "gpt-oss:120b"}, {"model": "qwen3:235b"}]},
            )
            return response

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://ollama.com/api", "ollama-key") == ["gpt-oss:120b", "qwen3:235b"]
        assert seen == [("https://ollama.com/api/tags", {"Authorization": "Bearer ollama-key"})]

    def test_unkeyed_anthropic_probe_can_use_curated_fallback(self, monkeypatch):
        _probe_urls_as_given(monkeypatch)

        def fake_get(url, headers=None, timeout=None, verify=None, **kwargs):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(model_routes.httpx, "get", fake_get)

        assert _probe_endpoint("https://api.anthropic.com/v1") == ANTHROPIC_MODELS

def test_endpoint_error_message_names_probed_url_and_probe_error():
    # Issue #25: the message carries the URL actually probed so the user can
    # self-diagnose, and picks the hint for the server the URL points at.
    msg = model_routes._model_endpoint_error_message(
        "http://localhost:11434/v1",
        {"error": "Connection refused"},
    )
    assert "Ollama" in msg
    assert "Connection refused" in msg
    assert "http://localhost:11434/v1" in msg

    msg = model_routes._model_endpoint_error_message(
        "https://api.example.com/v1",
        {"error": "HTTP 401"},
    )
    assert "HTTP 401" in msg
    assert "https://api.example.com/v1/models" in msg

    msg = model_routes._model_endpoint_error_message(
        "http://localhost:1234/v1",
        {"error": "HTTP 200"},  # 200-with-empty-list is the LM Studio trap
    )
    assert "LM Studio" in msg
    assert "http://localhost:1234/v1/models" in msg


def test_lmstudio_error_for_bare_host_port_probes_v1_models(monkeypatch):
    # Regression: build_models_url must add /v1 for path-less LM Studio URLs.
    # _is_ollama_native_url would otherwise match localhost+empty path and
    # route to /api/tags, masking the LM Studio URL we want to assert on.
    monkeypatch.setattr("src.llm_core._is_ollama_native_url", lambda url: False)
    msg = model_routes._model_endpoint_error_message(
        "http://localhost:1234",
        {"error": "HTTP 200"},
    )
    assert "LM Studio" in msg
    assert "http://localhost:1234/v1/models" in msg


# ── _rewrite_loopback_for_docker (issue #25: LM Studio on host loopback) ──

class TestDockerLoopbackRewrite:
    def test_rewrites_loopback_when_in_docker(self, monkeypatch):
        monkeypatch.setattr(model_routes, "_docker_host_gateway_reachable", lambda: True)
        assert (model_routes._rewrite_loopback_for_docker("http://localhost:1234/v1")
                == "http://host.docker.internal:1234/v1")
        assert (model_routes._rewrite_loopback_for_docker("http://127.0.0.1:1234/v1")
                == "http://host.docker.internal:1234/v1")

    def test_no_rewrite_when_not_in_docker(self, monkeypatch):
        monkeypatch.setattr(model_routes, "_docker_host_gateway_reachable", lambda: False)
        assert (model_routes._rewrite_loopback_for_docker("http://localhost:1234/v1")
                == "http://localhost:1234/v1")

    def test_non_loopback_untouched_even_in_docker(self, monkeypatch):
        # Cloud and LAN hosts must never be rewritten or they would break.
        monkeypatch.setattr(model_routes, "_docker_host_gateway_reachable", lambda: True)
        assert (model_routes._rewrite_loopback_for_docker("https://api.openai.com/v1")
                == "https://api.openai.com/v1")
        assert (model_routes._rewrite_loopback_for_docker("http://192.168.1.50:1234/v1")
                == "http://192.168.1.50:1234/v1")


class TestDockerHostGatewayReachable:
    def test_native_host_is_false_and_skips_dns(self, monkeypatch):
        monkeypatch.setattr(model_routes.os.path, "exists", lambda p: False)

        def _no_cgroup(*a, **k):
            raise FileNotFoundError

        monkeypatch.setattr("builtins.open", _no_cgroup)

        def _must_not_run(*a, **k):
            raise AssertionError("getaddrinfo must not run on native hosts")

        monkeypatch.setattr(model_routes.socket, "getaddrinfo", _must_not_run)
        assert model_routes._docker_host_gateway_reachable() is False

    def test_container_with_host_gateway_is_true(self, monkeypatch):
        monkeypatch.setattr(model_routes.os.path, "exists", lambda p: p == "/.dockerenv")
        monkeypatch.setattr(model_routes.socket, "getaddrinfo", lambda *a, **k: [("ok",)])
        assert model_routes._docker_host_gateway_reachable() is True

    def test_container_without_host_gateway_is_false(self, monkeypatch):
        monkeypatch.setattr(model_routes.os.path, "exists", lambda p: p == "/.dockerenv")

        def _fail(*a, **k):
            raise OSError("name or service not known")

        monkeypatch.setattr(model_routes.socket, "getaddrinfo", _fail)
        assert model_routes._docker_host_gateway_reachable() is False


# ── pinned model IDs: normalization helper ──


def test_normalize_model_ids_trims_dedupes_and_parses_strings():
    assert _normalize_model_ids([" a ", "a", "b", ""]) == ["a", "b"]
    assert _normalize_model_ids('["x", "y", "x"]') == ["x", "y"]
    assert _normalize_model_ids("a, b\n c ,a") == ["a", "b", "c"]
    assert _normalize_model_ids(None) == []
    assert _normalize_model_ids("   ") == []
    assert _normalize_model_ids([1, "ok", None, {"a": 1}]) == ["ok"]


def test_visible_models_merges_pinned_after_cached_and_honours_hidden():
    assert _visible_models(["a"], None, ["deploy-1"]) == ["a", "deploy-1"]
    assert _visible_models(["a", "b"], None, ["b", "c"]) == ["a", "b", "c"]
    assert _visible_models(["a"], ["deploy-1"], ["deploy-1"]) == ["a"]
    assert _visible_models('["a"]', '["a"]', '["b"]') == ["b"]
    # Non-JSON strings are comma/newline lists and never raise.
    assert _visible_models("a,b", "b", "{bad json") == ["a", "{bad json"]
    assert _visible_models("", None, "") == []


# ── pinned model IDs: route behaviour ──

@pytest.fixture(autouse=True)
def _python_multipart(monkeypatch):
    # Building the router registers Form() routes, which need python-multipart.
    try:
        import python_multipart  # noqa: F401
    except ImportError:
        stub = types.ModuleType("python_multipart")
        stub.__version__ = "0.0.13"
        monkeypatch.setitem(sys.modules, "python_multipart", stub)


class _RouteCondition:
    def __init__(self, op, field, value):
        self.op = op
        self.field = field
        self.value = value

    def __or__(self, other):
        return ("or", self, other)


class _RouteColumn:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return _RouteCondition("eq", self.name, value)

    def is_(self, value):
        return _RouteCondition("eq", self.name, value)

    def desc(self):
        return self


class _RouteModelEndpoint:
    """ModelEndpoint stand-in that stores constructor kwargs as attributes.

    Class-level fake columns let it double as the query class in the dedupe
    lookup; instance attributes (set in __init__) shadow them per-row.
    """

    id = _RouteColumn("id")
    base_url = _RouteColumn("base_url")
    is_enabled = _RouteColumn("is_enabled")
    owner = _RouteColumn("owner")
    created_at = _RouteColumn("created_at")

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _PinnedFakeRequest:
    def __init__(self, body=None, headers=None):
        self._body = body if body is not None else {}
        self.headers = headers or {}

    async def json(self):
        return self._body


def _admin_route(monkeypatch, rows, path, method):
    """Bind `rows` as the endpoint table and return the admin route handler."""
    db = _RouteDb(rows)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(model_routes, "require_admin", lambda request: None)
    router = model_routes.setup_model_routes(model_discovery=None)
    return db, _route_endpoint(router, path, method)


def _make_endpoint(**kwargs):
    base = dict(
        id="ep1",
        name="EP",
        base_url="http://localhost:9999/v1",
        api_key=None,
        is_enabled=True,
        hidden_models=None,
        cached_models=None,
        pinned_models=None,
        model_type="llm",
        supports_tools=None,
        endpoint_kind="auto",
        model_refresh_mode="auto",
        model_refresh_interval=None,
        model_refresh_timeout=None,
        owner=None,
        created_at=None,
        updated_at=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_patch_pinned_models_dedupes_and_leaves_hidden_alone(monkeypatch):
    ep = _make_endpoint(hidden_models=json.dumps(["hide-me"]))
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints/{ep_id}/models", "PATCH")

    request = _PinnedFakeRequest(body={"pinned_models": ["deploy-1", "deploy-1", "deploy-2"]})
    result = asyncio.run(endpoint("ep1", request))

    assert json.loads(ep.pinned_models) == ["deploy-1", "deploy-2"]
    assert result["pinned_count"] == 2
    assert json.loads(ep.hidden_models) == ["hide-me"]


def test_patch_api_hidden_payload_converts_to_pinned(monkeypatch):
    # An empty hidden list means every cached model is pinned, not none.
    for hidden, expected_pins in ((["m2"], ["m1", "m3"]), ([], ["m1", "m2", "m3"])):
        ep = _make_endpoint(
            base_url="https://openrouter.ai/api/v1",
            cached_models=json.dumps(["m1", "m2", "m3"]),
            pinned_models=None,
        )
        _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints/{ep_id}/models", "PATCH")

        result = asyncio.run(endpoint("ep1", _PinnedFakeRequest(body={"hidden": hidden})))

        assert result["pinned_count"] == len(expected_pins)
        assert result["hidden_count"] == 0
        assert json.loads(ep.pinned_models) == expected_pins
        assert ep.hidden_models is None


def test_get_models_returns_pinned_when_probe_empty(monkeypatch):
    ep = _make_endpoint(pinned_models=json.dumps(["deploy-1"]))
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *a, **k: [])
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints/{ep_id}/models", "GET")

    result = endpoint("ep1", _PinnedFakeRequest(), SimpleNamespace(headers={}))

    ids = [row["id"] for row in result]
    assert ids == ["deploy-1"]
    assert result[0]["is_pinned"] is True


def test_get_api_models_marks_picker_as_pinned_only(monkeypatch):
    ep = _make_endpoint(
        base_url="https://api.example.test/v1",
        cached_models=json.dumps(["openai/gpt-image-1", "anthropic/claude-sonnet-4"]),
        pinned_models=json.dumps(["openai/gpt-image-1"]),
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints/{ep_id}/models", "GET")

    result = endpoint("ep1", _PinnedFakeRequest(), SimpleNamespace(headers={}))

    by_id = {row["id"]: row for row in result}
    assert by_id["openai/gpt-image-1"]["picker_requires_pinning"] is True
    assert by_id["openai/gpt-image-1"]["is_pinned"] is True
    assert by_id["anthropic/claude-sonnet-4"]["picker_requires_pinning"] is True
    assert by_id["anthropic/claude-sonnet-4"]["is_pinned"] is False


def test_get_fresh_api_models_marks_cached_inventory_as_pinned(monkeypatch):
    ep = _make_endpoint(
        base_url="https://api.example.test/v1",
        cached_models=json.dumps(["openai/gpt-image-1", "anthropic/claude-sonnet-4"]),
        pinned_models=None,
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints/{ep_id}/models", "GET")

    result = endpoint("ep1", _PinnedFakeRequest(), SimpleNamespace(headers={}))

    assert [row["id"] for row in result] == [
        "openai/gpt-image-1",
        "anthropic/claude-sonnet-4",
    ]
    assert all(row["picker_requires_pinning"] is True for row in result)
    assert all(row["is_pinned"] is True for row in result)


def test_get_legacy_api_models_preserves_hidden_selection_as_pinned(monkeypatch):
    ep = _make_endpoint(
        base_url="https://api.example.test/v1",
        cached_models=json.dumps(["m1", "m2", "m3"]),
        hidden_models=json.dumps(["m2"]),
        pinned_models=None,
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints/{ep_id}/models", "GET")

    result = endpoint("ep1", _PinnedFakeRequest(), SimpleNamespace(headers={}))

    by_id = {row["id"]: row for row in result}
    assert by_id["m1"]["is_pinned"] is True
    assert by_id["m2"]["is_pinned"] is False
    assert by_id["m3"]["is_pinned"] is True


def test_reprobe_preserves_pinned_models(monkeypatch):
    ep = _make_endpoint(pinned_models=json.dumps(["deploy-1"]))
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *a, **k: ["m1"])
    monkeypatch.setattr(model_routes, "_is_chat_model", lambda m: True)
    monkeypatch.setattr(
        model_routes, "_probe_single_model", lambda *a, **k: {"status": "ok"}
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints/{ep_id}/probe", "GET")

    response = endpoint("ep1", _PinnedFakeRequest())

    async def _drain():
        async for _ in response.body_iterator:
            pass

    asyncio.run(_drain())

    # Probe rewrites cached/hidden but must never touch admin-pinned IDs.
    assert json.loads(ep.pinned_models) == ["deploy-1"]
    assert json.loads(ep.cached_models) == ["m1"]


def test_reprobe_chatgpt_subscription_does_not_hide_models(monkeypatch):
    # The whole point of the _probe_single_model short-circuit is that re-probing
    # a chatgpt-subscription endpoint must NOT mark every (un-probeable) model as
    # failed and write them all into hidden_models. Assert that end-to-end at the
    # route level, with the REAL _probe_single_model doing the skip.
    ep = _make_endpoint(
        base_url="https://chatgpt.com/backend-api/codex",
        api_key=None,
        hidden_models=json.dumps(["stale-hidden"]),
    )
    monkeypatch.setattr(model_routes, "_normalize_base", lambda url: url.rstrip("/"))
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *a, **k: ["gpt-5.1-codex", "gpt-5.1"])
    monkeypatch.setattr(model_routes, "_is_chat_model", lambda m: True)
    # Any completion probe would be a bug for this provider.
    monkeypatch.setattr(
        model_routes.httpx, "post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not probe chatgpt-subscription")),
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints/{ep_id}/probe", "GET")

    response = endpoint("ep1", _PinnedFakeRequest())
    chunks = []

    async def _drain():
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    asyncio.run(_drain())

    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    done = next(e for e in events if e.get("type") == "probe_done")
    results = [e for e in events if e.get("type") == "probe_result"]

    # Every model was skipped as ok; none failed → nothing hidden.
    assert done["hidden"] == 0
    assert done["ok"] == len(results) == 2
    assert all(r["status"] == "ok" and r.get("skipped") is True for r in results)
    # The stale hidden_models is cleared, not repopulated with every model.
    assert ep.hidden_models is None


def test_api_key_fingerprint_is_stable_and_non_secret():
    fp_one = _api_key_fingerprint("key-one")

    assert _api_key_fingerprint("") == ""
    assert fp_one == _api_key_fingerprint(" key-one ")
    assert fp_one != _api_key_fingerprint("key-two")
    assert len(fp_one) == 8
    assert "key-one" not in fp_one


def _create_form_kwargs(**overrides):
    """Defaults for every Form() param create_model_endpoint reads directly.

    Calling the route as a plain function bypasses FastAPI form parsing, so the
    Form() sentinels must be replaced with real strings.
    """
    kwargs = dict(
        name="",
        api_key="",
        skip_probe="true",  # avoid any network probe in unit tests
        require_models="false",
        model_type="llm",
        endpoint_kind="auto",
        model_refresh_mode="",
        model_refresh_interval="",
        model_refresh_timeout="",
        supports_tools="",
        pinned_models="",
        container_local="false",
        shared="true",
    )
    kwargs.update(overrides)
    return kwargs


def _patch_create_deps(monkeypatch, db, settings=None):
    import src.auth_helpers as auth_helpers
    # Shared, in-memory settings so the auto-default write path stays hermetic
    # (no real settings.json). Returned so tests can assert what was persisted.
    settings = {"default_endpoint_id": "exists"} if settings is None else settings
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(model_routes, "require_admin", lambda request: None)
    monkeypatch.setattr(model_routes, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(model_routes, "_normalize_base", lambda b: b)
    monkeypatch.setattr(model_routes, "_rewrite_loopback_for_docker", lambda b, **k: b)
    monkeypatch.setattr(model_routes, "_load_settings", lambda: settings)
    monkeypatch.setattr(model_routes, "_save_settings", lambda s: settings.update(s))
    monkeypatch.setattr(endpoint_resolver, "resolve_url", lambda u: u)
    monkeypatch.setattr(auth_helpers, "get_current_user", lambda req: None)
    router = model_routes.setup_model_routes(model_discovery=None)
    return settings, _route_endpoint(router, "/api/model-endpoints", "POST")


def test_list_model_endpoints_returns_key_fingerprint(monkeypatch):
    endpoint_with_key = _make_endpoint(
        api_key="key-one",
        cached_models=json.dumps(["m1"]),
    )
    endpoint_without_key = _make_endpoint(
        id="ep2",
        api_key=None,
        cached_models=json.dumps(["m2"]),
    )
    _, endpoint = _admin_route(monkeypatch, [endpoint_with_key, endpoint_without_key], "/api/model-endpoints", "GET")

    result = endpoint(_PinnedFakeRequest())

    assert result[0]["has_key"] is True
    assert result[0]["api_key_fingerprint"] == _api_key_fingerprint("key-one")
    assert result[1]["has_key"] is False
    assert result[1]["api_key_fingerprint"] == ""


def test_list_api_endpoint_defaults_inventory_to_visible_when_none_pinned(monkeypatch):
    ep = _make_endpoint(
        base_url="https://api.example.test/v1",
        cached_models=json.dumps(["openai/gpt-image-1", "anthropic/claude-sonnet-4"]),
        pinned_models=None,
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints", "GET")

    result = endpoint(_PinnedFakeRequest())

    assert result[0]["models"] == [
        "openai/gpt-image-1",
        "anthropic/claude-sonnet-4",
    ]
    assert result[0]["pinned_models"] == result[0]["models"]
    assert result[0]["model_count"] == 2
    assert result[0]["picker_requires_pinning"] is True
    assert result[0]["status"] == "online"


def test_api_picker_preserves_explicit_empty_selection():
    ep = _make_endpoint(
        base_url="https://api.example.test/v1",
        cached_models=json.dumps(["openai/gpt-image-1", "anthropic/claude-sonnet-4"]),
        pinned_models=json.dumps([]),
    )

    models, pinned = model_routes._picker_models_for_endpoint(
        ep, ep.base_url, ep.endpoint_kind
    )

    assert models == []
    assert pinned == []


def test_list_api_endpoint_returns_pinned_picker_models(monkeypatch):
    ep = _make_endpoint(
        base_url="https://api.example.test/v1",
        cached_models=json.dumps(["openai/gpt-image-1", "anthropic/claude-sonnet-4"]),
        pinned_models=json.dumps(["openai/gpt-image-1"]),
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints", "GET")

    result = endpoint(_PinnedFakeRequest())

    assert result[0]["models"] == ["openai/gpt-image-1"]
    assert result[0]["pinned_models"] == ["openai/gpt-image-1"]
    assert result[0]["model_count"] == 2


def test_list_api_endpoint_pinned_models_ignore_stale_hidden_state(monkeypatch):
    ep = _make_endpoint(
        base_url="https://api.example.test/v1",
        cached_models=json.dumps(["openai/gpt-image-1", "anthropic/claude-sonnet-4"]),
        hidden_models=json.dumps(["openai/gpt-image-1"]),
        pinned_models=json.dumps(["openai/gpt-image-1"]),
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints", "GET")

    result = endpoint(_PinnedFakeRequest())

    assert result[0]["models"] == ["openai/gpt-image-1"]


def test_list_api_endpoint_derives_pins_from_legacy_hidden_state(monkeypatch):
    ep = _make_endpoint(
        base_url="https://openrouter.ai/api/v1",
        cached_models=json.dumps(["m1", "m2", "m3"]),
        hidden_models=json.dumps(["m2"]),
        pinned_models=None,
    )
    _, endpoint = _admin_route(monkeypatch, [ep], "/api/model-endpoints", "GET")

    result = endpoint(_PinnedFakeRequest())

    assert result[0]["models"] == ["m1", "m3"]
    assert result[0]["pinned_models"] == ["m1", "m3"]
    assert json.loads(ep.pinned_models) == ["m1", "m3"]


def test_post_creates_endpoint_with_pinned_models(monkeypatch):
    db = _RouteDb([])  # no existing row → fresh create path
    _, create = _patch_create_deps(monkeypatch, db)

    result = create(
        _PinnedFakeRequest(),
        base_url="http://host:1234/v1",
        **_create_form_kwargs(pinned_models="deploy-1, deploy-1\ndeploy-2"),
    )

    assert result["pinned_models"] == ["deploy-1", "deploy-2"]
    assert result["models"] == ["deploy-1", "deploy-2"]
    assert result["online"] is True
    # Persisted onto the created row.
    assert len(db.added) == 1
    assert json.loads(db.added[0].pinned_models) == ["deploy-1", "deploy-2"]


def test_post_google_endpoint_defaults_to_manual_refresh_when_mode_omitted(monkeypatch):
    db = _RouteDb([])
    _, create = _patch_create_deps(monkeypatch, db)
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *args, **kwargs: ["gemini-test"])

    create(
        _PinnedFakeRequest(),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        **_create_form_kwargs(
            api_key="google-key",
            endpoint_kind="api",
            model_refresh_mode="",
        ),
    )

    assert len(db.added) == 1
    assert db.added[0].model_refresh_mode == "manual"


def test_post_dedupe_existing_merges_and_returns_pinned(monkeypatch):
    existing = _make_endpoint(
        base_url="http://host:1234/v1",
        cached_models=json.dumps(["m1"]),
        hidden_models=None,
        pinned_models=json.dumps(["old-pin"]),
    )
    db = _RouteDb([existing])
    _, create = _patch_create_deps(monkeypatch, db)

    result = create(
        _PinnedFakeRequest(),
        base_url="http://host:1234/v1",
        **_create_form_kwargs(pinned_models="new-pin"),
    )

    assert result["existing"] is True
    # Incoming pin merged onto the existing pins (no clobber, order preserved).
    assert json.loads(existing.pinned_models) == ["old-pin", "new-pin"]
    assert result["pinned_models"] == ["old-pin", "new-pin"]
    # models = cached + pinned - hidden, visible merged list.
    assert result["models"] == ["m1", "old-pin", "new-pin"]
    # No new row created on the dedupe path.
    assert db.added == []


def test_post_dedupe_existing_does_not_clobber_pinned_when_omitted(monkeypatch):
    existing = _make_endpoint(
        base_url="http://host:1234/v1",
        cached_models=json.dumps(["m1"]),
        pinned_models=json.dumps(["keep-me"]),
    )
    db = _RouteDb([existing])
    _, create = _patch_create_deps(monkeypatch, db)

    result = create(
        _PinnedFakeRequest(),
        base_url="http://host:1234/v1",
        **_create_form_kwargs(),  # pinned_models defaults to ""
    )

    assert json.loads(existing.pinned_models) == ["keep-me"]
    assert result["pinned_models"] == ["keep-me"]
    assert db.committed == 0  # nothing to persist


def test_post_same_base_url_different_api_key_creates_distinct_endpoint(monkeypatch):
    existing = _make_endpoint(
        base_url="https://api.example.test/v1",
        api_key="key-one",
    )
    db = _RouteDb([existing])
    _, create = _patch_create_deps(monkeypatch, db)

    result = create(
        _PinnedFakeRequest(),
        base_url="https://api.example.test/v1",
        **_create_form_kwargs(api_key="key-two"),
    )

    assert result.get("existing") is not True
    assert result["has_key"] is True
    assert result["api_key_fingerprint"] == _api_key_fingerprint("key-two")
    assert len(db.added) == 1
    assert db.added[0].base_url == "https://api.example.test/v1"
    assert db.added[0].api_key == "key-two"


def test_post_reassigns_default_when_current_default_disabled(monkeypatch):
    # #3586: the configured default points at a now-disabled endpoint. Adding a
    # new endpoint must promote it to the default, otherwise raw-setting readers
    # (Memory → Tidy) keep failing with "No default model configured".
    disabled = _make_endpoint(id="dead", base_url="http://old-host/v1", is_enabled=False)
    db = _RouteDb([disabled])
    settings, create = _patch_create_deps(
        monkeypatch, db, settings={"default_endpoint_id": "dead", "default_model": "stale"}
    )

    create(
        _PinnedFakeRequest(),
        base_url="http://new-host:1234/v1",
        **_create_form_kwargs(),
    )

    new_id = db.added[0].id
    assert settings["default_endpoint_id"] == new_id
    assert settings["default_endpoint_id"] != "dead"


def test_post_keeps_default_when_current_default_enabled(monkeypatch):
    # Counter-case: an enabled default must be left untouched when another
    # endpoint is added.
    live = _make_endpoint(id="live", base_url="http://live-host/v1", is_enabled=True)
    db = _RouteDb([live])
    settings, create = _patch_create_deps(
        monkeypatch, db, settings={"default_endpoint_id": "live", "default_model": "live-model"}
    )

    create(
        _PinnedFakeRequest(),
        base_url="http://another-host:1234/v1",
        **_create_form_kwargs(),
    )

    assert settings["default_endpoint_id"] == "live"
    assert settings["default_model"] == "live-model"


def test_post_same_base_url_same_api_key_still_dedupes(monkeypatch):
    existing = _make_endpoint(
        base_url="https://api.example.test/v1",
        api_key="key-one",
    )
    db = _RouteDb([existing])
    _, create = _patch_create_deps(monkeypatch, db)

    result = create(
        _PinnedFakeRequest(),
        base_url="https://api.example.test/v1",
        **_create_form_kwargs(api_key="key-one"),
    )

    assert result["existing"] is True
    assert result["id"] == existing.id
    assert result["has_key"] is True
    assert result["api_key_fingerprint"] == _api_key_fingerprint("key-one")
    assert db.added == []


class _RouteQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *conditions):
        for condition in conditions:
            if isinstance(condition, _RouteCondition) and condition.op == "eq":
                self.rows = [row for row in self.rows if getattr(row, condition.field, None) == condition.value]
            elif isinstance(condition, tuple) and condition and condition[0] == "or":
                keep = []
                for row in self.rows:
                    matched = False
                    for part in condition[1:]:
                        if isinstance(part, _RouteCondition) and part.op == "eq":
                            matched = matched or (getattr(row, part.field, None) == part.value)
                    if matched:
                        keep.append(row)
                self.rows = keep
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class _RouteDb:
    def __init__(self, rows):
        self.rows = rows
        self.added = []
        self.committed = 0
        self.commits = 0
        self.closed = False

    def query(self, model):
        return _RouteQuery(self.rows)

    def commit(self):
        self.committed += 1
        self.commits += 1

    def close(self):
        self.closed = True

    def add(self, row):
        self.rows.append(row)
        self.added.append(row)


class _ImmediateThread:
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


class _NoopThread:
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        return None


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _route_endpoint(router, path, method="GET"):
    for route in router.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} route not found")


def _route_ep(
    id,
    base_url,
    *,
    cached_models=None,
    endpoint_kind="auto",
    api_key=None,
    name=None,
    pinned_models=None,
    refresh_mode="auto",
    refresh_timeout=None,
    owner=None,
):
    return SimpleNamespace(
        id=id,
        name=name or id,
        base_url=base_url,
        api_key=api_key,
        is_enabled=True,
        cached_models=json.dumps(cached_models) if cached_models is not None else None,
        hidden_models=None,
        pinned_models=json.dumps(pinned_models) if pinned_models is not None else None,
        model_type="llm",
        endpoint_kind=endpoint_kind,
        model_refresh_mode=refresh_mode,
        model_refresh_interval=None,
        model_refresh_timeout=refresh_timeout,
        supports_tools=None,
        owner=owner,
        created_at=None,
        updated_at=None,
    )


def _route_request():
    return SimpleNamespace(
        state=SimpleNamespace(current_user=None),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=None)),
    )


def _models_route(monkeypatch, rows):
    """Bind `rows` as the endpoint table with auth off; return GET /api/models."""
    db = _RouteDb(rows)
    monkeypatch.setattr(model_routes, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(model_routes, "_auth_disabled", lambda: True)
    monkeypatch.setattr(model_routes, "build_chat_url", lambda base: f"{base}/chat/completions")
    router = model_routes.setup_model_routes(model_discovery=None)
    return db, _route_endpoint(router, "/api/models")


def test_api_models_rejects_api_token_without_chat_scope(monkeypatch):
    router = model_routes.setup_model_routes(model_discovery=None)

    def fail_session():
        raise AssertionError("model DB should not be queried without chat scope")

    monkeypatch.setattr(model_routes, "SessionLocal", fail_session)

    request = SimpleNamespace(
        state=SimpleNamespace(
            current_user="api",
            api_token=True,
            api_token_owner="alice",
            api_token_scopes=["documents:read"],
        ),
        app=SimpleNamespace(
            state=SimpleNamespace(
                auth_manager=SimpleNamespace(is_configured=True, is_admin=lambda user: False),
            ),
        ),
    )

    with pytest.raises(HTTPException) as exc:
        _route_endpoint(router, "/api/models")(request)

    assert exc.value.status_code == 403
    assert "chat" in str(exc.value.detail)


def test_api_models_scopes_api_token_to_token_owner(monkeypatch):
    rows = [
        _route_ep("alice", "http://alice.example/v1", cached_models=["alice-model"], owner="alice"),
        _route_ep("shared", "http://shared.example/v1", cached_models=["shared-model"], owner=None),
        _route_ep("bob", "http://bob.example/v1", cached_models=["bob-model"], owner="bob"),
    ]
    db = _RouteDb(rows)
    router = model_routes.setup_model_routes(model_discovery=None)
    admin_checks = []

    monkeypatch.setattr(model_routes, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(threading, "Thread", _NoopThread)

    request = SimpleNamespace(
        state=SimpleNamespace(
            current_user="api",
            api_token=True,
            api_token_owner="alice",
            api_token_scopes=["chat"],
        ),
        app=SimpleNamespace(
            state=SimpleNamespace(
                auth_manager=SimpleNamespace(
                    is_configured=True,
                    is_admin=lambda user: admin_checks.append(user) or False,
                ),
            ),
        ),
    )

    result = _route_endpoint(router, "/api/models")(request)

    assert [item["endpoint_name"] for item in result["items"]] == ["alice", "shared"]
    assert admin_checks == ["alice"]


def test_api_models_returns_only_pinned_proxy_models_without_refresh_probe(monkeypatch):
    row = _route_ep(
        "proxy",
        "http://100.117.136.97:34521/v1",
        cached_models=["cached-model", "other-model"],
        pinned_models=["cached-model"],
        endpoint_kind="proxy",
        api_key="fake-key",
        refresh_mode="manual",
    )
    _, list_models = _models_route(monkeypatch, [row])

    def fail_probe(*args, **kwargs):
        raise AssertionError("/models probe should not run for cached manual proxy")

    monkeypatch.setattr(model_routes, "_probe_endpoint", fail_probe)
    monkeypatch.setattr(threading, "Thread", _ImmediateThread)

    result = list_models(_route_request())

    assert result["items"][0]["models"] == ["cached-model"]
    assert result["items"][0]["models_extra"] == []
    assert result["items"][0]["category"] == "api"
    assert result["items"][0]["endpoint_kind"] == "proxy"
    assert "offline" not in result["items"][0]
    assert json.loads(row.cached_models) == ["cached-model", "other-model"]


def test_api_models_openrouter_uses_pinned_models_not_hidden(monkeypatch):
    row = _route_ep(
        "openrouter",
        "https://openrouter.ai/api/v1",
        cached_models=["openai/gpt-image-1", "anthropic/claude-sonnet-4"],
        pinned_models=["openai/gpt-image-1"],
        api_key="fake-key",
    )
    row.hidden_models = json.dumps(["openai/gpt-image-1"])
    _, list_models = _models_route(monkeypatch, [row])
    monkeypatch.setattr(threading, "Thread", _NoopThread)

    result = list_models(_route_request())

    assert result["items"][0]["endpoint_name"] == "openrouter"
    assert result["items"][0]["category"] == "api"
    assert result["items"][0]["models"] == ["openai/gpt-image-1"]


def test_api_models_openrouter_defaults_cached_models_visible(monkeypatch):
    row = _route_ep(
        "openrouter",
        "https://openrouter.ai/api/v1",
        cached_models=["m1", "m2", "m3"],
        pinned_models=None,
        api_key="fake-key",
    )
    _, list_models = _models_route(monkeypatch, [row])
    monkeypatch.setattr(threading, "Thread", _NoopThread)

    result = list_models(_route_request())

    assert result["items"][0]["endpoint_name"] == "openrouter"
    assert result["items"][0]["models"] == ["m1", "m2", "m3"]


@pytest.mark.asyncio
async def test_probe_local_skips_tailscale_proxy_endpoint(monkeypatch):
    proxy = _route_ep(
        "proxy",
        "http://100.117.136.97:34521/v1",
        cached_models=["cached-model"],
        endpoint_kind="proxy",
        api_key="fake-key",
    )
    local = _route_ep("local", "http://127.0.0.1:8000/v1", endpoint_kind="local")
    db = _RouteDb([proxy, local])
    router = model_routes.setup_model_routes(model_discovery=None)

    monkeypatch.setattr(model_routes, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(model_routes, "require_admin", lambda request: None)
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *a, **k: (_ for _ in ()).throw(AssertionError("full probe should not run")))

    pinged = []

    def fake_ping(base_url, api_key=None, timeout=1.5):
        pinged.append(base_url)
        return {"reachable": True, "status_code": 404, "error": "HTTP 404"}

    monkeypatch.setattr(model_routes, "_ping_endpoint", fake_ping)

    result = await _route_endpoint(router, "/api/model-endpoints/probe-local")(_route_request())

    assert set(result) == {"local"}
    assert pinged == ["http://127.0.0.1:8000/v1"]


def test_background_refresh_deduplicates_same_base_url(monkeypatch):
    ep1 = _route_ep("a", "http://127.0.0.1:8000/v1", endpoint_kind="local")
    ep2 = _route_ep("b", "http://127.0.0.1:8000/v1", endpoint_kind="local")
    _, list_models = _models_route(monkeypatch, [ep1, ep2])

    calls = []
    probe_done = threading.Event()

    def fake_probe(base_url, api_key=None, timeout=2):
        calls.append(base_url)
        probe_done.set()
        return ["live-model"]

    monkeypatch.setattr(model_routes, "_probe_endpoint", fake_probe)

    list_models(_route_request(), refresh=True)

    assert probe_done.wait(2)
    assert _wait_for(lambda: ep1.cached_models and ep2.cached_models)
    assert calls == ["http://127.0.0.1:8000/v1"]
    assert json.loads(ep1.cached_models) == ["live-model"]
    assert json.loads(ep2.cached_models) == ["live-model"]


def test_picker_refresh_waits_for_discovered_models(monkeypatch):
    ep = _route_ep("local", "http://127.0.0.1:8000/v1", endpoint_kind="local")
    _, list_models = _models_route(monkeypatch, [ep])
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *a, **k: ["new-model"])

    result = list_models(_route_request(), refresh=True, wait_refresh=True)

    assert result["items"][0]["models"] == ["new-model"]


def test_background_refresh_failure_keeps_existing_cached_models(monkeypatch):
    ep = _route_ep(
        "local",
        "http://127.0.0.1:8000/v1",
        cached_models=["cached-model"],
        endpoint_kind="local",
    )
    db, list_models = _models_route(monkeypatch, [ep])
    probe_done = threading.Event()

    def fake_probe(*args, **kwargs):
        probe_done.set()
        return []

    monkeypatch.setattr(model_routes, "_probe_endpoint", fake_probe)

    result = list_models(_route_request(), refresh=True)

    assert probe_done.wait(2)
    assert _wait_for(lambda: db.commits > 0)
    assert result["items"][0]["models"] == ["cached-model"]
    assert json.loads(ep.cached_models) == ["cached-model"]


def test_api_models_auth_gate_fails_closed_on_unexpected_error(monkeypatch):
    """A non-HTTPException raised while checking auth must yield 500, not a
    silent pass-through that leaks the model list to an unauthenticated caller."""
    router = model_routes.setup_model_routes(model_discovery=None)

    monkeypatch.setattr(model_routes, "_auth_disabled", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    request = SimpleNamespace(
        state=SimpleNamespace(current_user=None),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=SimpleNamespace(is_configured=True))),
    )

    with pytest.raises(HTTPException) as exc:
        _route_endpoint(router, "/api/models")(request)

    assert exc.value.status_code == 500


def test_llm_core_list_model_ids_uses_cached_configured_proxy(monkeypatch):
    ep = _route_ep(
        "proxy",
        "http://100.117.136.97:34521/v1",
        cached_models=["cached-model", "hidden-model"],
        endpoint_kind="proxy",
    )
    ep.hidden_models = json.dumps(["hidden-model"])
    db = _RouteDb([ep])

    monkeypatch.setattr(src_database, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(src_database, "SessionLocal", lambda: db)
    monkeypatch.setattr(llm_core.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("/models should not be fetched")))

    assert llm_core.list_model_ids("http://100.117.136.97:34521/v1/chat/completions", timeout=1) == ["cached-model"]


def test_explicit_proxy_test_fetches_models_with_long_timeout(monkeypatch):
    router = model_routes.setup_model_routes(model_discovery=None)

    monkeypatch.setattr(model_routes, "require_admin", lambda request: None)
    monkeypatch.setattr(model_routes, "_ping_endpoint", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ping should not run when model listing succeeds")))

    calls = []
    returned = ["NVIDIA NIM/openai/gpt-oss-120b", "mistral/mistral-small-2603"]

    def fake_probe(base_url, api_key=None, timeout=2):
        calls.append({"base_url": base_url, "api_key": api_key, "timeout": timeout})
        return returned

    monkeypatch.setattr(model_routes, "_probe_endpoint", fake_probe)

    result = _route_endpoint(router, "/api/model-endpoints/test", "POST")(
        _route_request(),
        base_url="http://100.117.136.97:34521/v1",
        api_key="fake-key",
        endpoint_kind="proxy",
    )

    assert result["online"] is True
    assert result["status"] == "online"
    assert result["models"] == returned
    assert calls == [{
        "base_url": "http://100.117.136.97:34521/v1",
        "api_key": "fake-key",
        "timeout": 30.0,
    }]


def test_explicit_proxy_add_fetches_and_caches_models_with_long_timeout(monkeypatch):
    db = _RouteDb([])
    router = model_routes.setup_model_routes(model_discovery=None)

    monkeypatch.setattr(model_routes, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(model_routes, "require_admin", lambda request: None)
    monkeypatch.setattr(model_routes, "_load_settings", lambda: {})
    monkeypatch.setattr(model_routes, "_save_settings", lambda settings: None)
    monkeypatch.setattr("src.auth_helpers.get_current_user", lambda request: None)
    monkeypatch.setattr(model_routes, "_ping_endpoint", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ping should not run when model listing succeeds")))

    calls = []
    returned = ["NVIDIA NIM/openai/gpt-oss-120b", "mistral/mistral-small-2603"]

    def fake_probe(base_url, api_key=None, timeout=2):
        calls.append({"base_url": base_url, "api_key": api_key, "timeout": timeout})
        return returned

    monkeypatch.setattr(model_routes, "_probe_endpoint", fake_probe)

    result = _route_endpoint(router, "/api/model-endpoints", "POST")(
        _route_request(),
        name="Bifrost",
        base_url="http://100.117.136.97:34521/v1",
        api_key="fake-key",
        skip_probe="true",
        require_models="false",
        model_type="llm",
        endpoint_kind="proxy",
        model_refresh_mode="manual",
        model_refresh_interval="",
        model_refresh_timeout="",
        supports_tools="",
        container_local="false",
        shared="true",
    )

    assert result["online"] is True
    assert result["status"] == "online"
    assert result["models"] == returned
    assert calls == [{
        "base_url": "http://100.117.136.97:34521/v1",
        "api_key": "fake-key",
        "timeout": 30.0,
    }]
    assert len(db.rows) == 1
    assert json.loads(db.rows[0].cached_models) == returned
    assert db.rows[0].endpoint_kind == "proxy"
    assert db.rows[0].model_refresh_mode == "manual"


def test_manual_refresh_uses_long_timeout_and_saves_full_model_list(monkeypatch):
    ep = _route_ep(
        "proxy",
        "http://100.117.136.97:34521/v1",
        cached_models=["cached-model"],
        endpoint_kind="proxy",
        api_key="fake-key",
        refresh_mode="manual",
    )
    db = _RouteDb([ep])
    router = model_routes.setup_model_routes(model_discovery=None)

    monkeypatch.setattr(model_routes, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(model_routes, "require_admin", lambda request: None)

    calls = []
    refreshed = ["cached-model", "mistral/mistral-small-2603", "provider/nested/model/id"]

    def fake_probe(base_url, api_key=None, timeout=2):
        calls.append({"base_url": base_url, "api_key": api_key, "timeout": timeout})
        return refreshed

    monkeypatch.setattr(model_routes, "_probe_endpoint", fake_probe)

    response = SimpleNamespace(headers={})
    result = _route_endpoint(router, "/api/model-endpoints/{ep_id}/models")(
        "proxy",
        _route_request(),
        response,
        refresh=True,
        refresh_timeout=60,
    )

    assert [m["id"] for m in result] == refreshed
    assert calls == [{
        "base_url": "http://100.117.136.97:34521/v1",
        "api_key": "fake-key",
        "timeout": 60.0,
    }]
    assert json.loads(ep.cached_models) == refreshed
    assert db.commits == 1
    assert response.headers["X-Model-Refresh-Status"] == "refreshed"
    assert response.headers["X-Model-Refresh-Count"] == "3"


def test_manual_refresh_defaults_to_proxy_long_timeout(monkeypatch):
    ep = _route_ep(
        "proxy",
        "https://proxy.example.test/v1",
        cached_models=["cached-model"],
        endpoint_kind="proxy",
        refresh_mode="manual",
    )
    db = _RouteDb([ep])
    router = model_routes.setup_model_routes(model_discovery=None)

    monkeypatch.setattr(model_routes, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(model_routes, "require_admin", lambda request: None)

    timeouts = []

    def fake_probe(base_url, api_key=None, timeout=2):
        timeouts.append(timeout)
        return ["cached-model", "new-model"]

    monkeypatch.setattr(model_routes, "_probe_endpoint", fake_probe)

    response = SimpleNamespace(headers={})
    _route_endpoint(router, "/api/model-endpoints/{ep_id}/models")(
        "proxy",
        _route_request(),
        response,
        refresh=True,
    )

    assert timeouts == [30.0]
    assert json.loads(ep.cached_models) == ["cached-model", "new-model"]


def test_manual_refresh_timeout_keeps_cached_models_and_warns(monkeypatch):
    ep = _route_ep(
        "proxy",
        "http://100.117.136.97:34521/v1",
        cached_models=["cached-model"],
        endpoint_kind="proxy",
        api_key="fake-key",
        refresh_mode="manual",
    )
    db = _RouteDb([ep])
    router = model_routes.setup_model_routes(model_discovery=None)

    monkeypatch.setattr(model_routes, "ModelEndpoint", _RouteModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: db)
    monkeypatch.setattr(model_routes, "require_admin", lambda request: None)

    def fake_probe(base_url, api_key=None, timeout=2):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(model_routes, "_probe_endpoint", fake_probe)

    response = SimpleNamespace(headers={})
    result = _route_endpoint(router, "/api/model-endpoints/{ep_id}/models")(
        "proxy",
        _route_request(),
        response,
        refresh=True,
        refresh_timeout=60,
    )

    assert [m["id"] for m in result] == ["cached-model"]
    assert json.loads(ep.cached_models) == ["cached-model"]
    assert db.commits == 0
    assert response.headers["X-Model-Refresh-Status"] == "failed"
    assert "kept cached models" in response.headers["X-Model-Refresh-Warning"]
