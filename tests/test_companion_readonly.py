"""Owner-scope tests for the read-only companion bridge.

Mirrors the direct-helper style of tests/test_null_owner_gates.py: exercise the
small pure helpers against mock request state and owner values, so the scoping
rule can't silently regress. A bearer token for owner A must never see owner B's
rows, and legacy null-owner rows must not widen a token's access.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import core.database
import src.endpoint_resolver

from companion.routes import setup_companion_routes, owner_can_see
from tests.helpers.routes import route_endpoint


def _request(**state):
    return SimpleNamespace(state=SimpleNamespace(**state))


class _Predicate:
    def __init__(self, check):
        self._check = check

    def __call__(self, row):
        return self._check(row)

    def __or__(self, other):
        return _Predicate(lambda row: self(row) or other(row))


class _Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):  # noqa: D401
        return _Predicate(lambda row: getattr(row, self.name) == value)


class _ModelEndpoint:
    is_enabled = _Column("is_enabled")
    model_type = _Column("model_type")
    owner = _Column("owner")


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *predicates):
        self._rows = [
            row for row in self._rows
            if all(predicate(row) for predicate in predicates)
        ]
        return self

    def all(self):
        return list(self._rows)


class _DB:
    def __init__(self, rows):
        self._rows = rows
        self.closed = False

    def query(self, model):
        assert model is _ModelEndpoint
        return _Query(self._rows)

    def close(self):
        self.closed = True


def _ep(
    id,
    name,
    owner,
    *,
    is_enabled=True,
    model_type="llm",
    base_url=None,
    cached_models=None,
    hidden_models=None,
    supports_tools=False,
    api_key="secret-key",
):
    return SimpleNamespace(
        id=id,
        name=name,
        owner=owner,
        is_enabled=is_enabled,
        model_type=model_type,
        base_url=base_url or f"https://{name}.example/v1",
        cached_models=json.dumps(cached_models or [f"{name}-model"]),
        hidden_models=json.dumps(hidden_models or []),
        supports_tools=supports_tools,
        api_key=api_key,
        headers={"Authorization": "Bearer secret-header"},
    )


def _models_route():
    return route_endpoint(setup_companion_routes(), "/api/companion/models", "GET")


def _call_models_route(monkeypatch, rows, request):
    db = _DB(rows)
    monkeypatch.setattr(core.database, "SessionLocal", lambda: db)
    monkeypatch.setattr(core.database, "ModelEndpoint", _ModelEndpoint)

    monkeypatch.setattr(
        src.endpoint_resolver,
        "build_chat_url",
        lambda base_url: f"{base_url.rstrip('/')}/chat/completions",
    )

    response = _models_route()(request)
    assert db.closed is True
    return response["endpoints"]


def _endpoint_names(endpoints):
    return [endpoint["name"] for endpoint in endpoints]


# --- owner_can_see: the read-scope rule ------------------------------------

def test_owner_sees_their_own_rows():
    assert owner_can_see("alice", "alice") is True


def test_null_owner_shared_rows_are_visible():
    # Legacy shared rows (owner is None) are visible to everyone by design...
    assert owner_can_see(None, "alice") is True


def test_null_owner_does_not_widen_access_to_others_rows():
    # ...but a null-owner row must not be a backdoor to another OWNER's rows.
    assert owner_can_see("bob", "alice") is False


def test_cross_owner_is_blocked():
    assert owner_can_see("bob", "alice") is False
    assert owner_can_see("alice", "bob") is False


def test_unauthenticated_owner_sees_only_shared_rows():
    # owner=None (no resolved caller): only null-owner shared rows are visible,
    # never any owned row.
    assert owner_can_see(None, None) is True
    assert owner_can_see("alice", None) is False


# --- GET /api/companion/models: route-level scoping -----------------------

def test_models_route_scopes_cookie_user_to_owned_and_shared_rows(monkeypatch):
    rows = [
        _ep(1, "alice-endpoint", "alice"),
        _ep(2, "shared-endpoint", None),
        _ep(3, "bob-endpoint", "bob"),
    ]
    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user="alice"),
    )

    assert _endpoint_names(endpoints) == ["alice-endpoint", "shared-endpoint"]


def test_models_route_scopes_api_token_to_token_owner(monkeypatch):
    rows = [
        _ep(1, "alice-endpoint", "alice"),
        _ep(2, "shared-endpoint", None),
        _ep(3, "bob-endpoint", "bob"),
    ]
    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(
            api_token=True,
            api_token_owner="alice",
            api_token_scopes=["chat"],
            current_user="api",
        ),
    )

    assert _endpoint_names(endpoints) == ["alice-endpoint", "shared-endpoint"]


def test_models_route_rejects_api_token_without_chat_scope(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _models_route()(
            _request(
                api_token=True,
                api_token_owner="alice",
                api_token_scopes=["todos:read"],
                current_user="api",
            )
        )

    assert exc.value.status_code == 403
    assert "scope: chat" in exc.value.detail


def test_models_route_rejects_ownerless_api_token(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")

    with pytest.raises(HTTPException) as exc:
        _models_route()(
            _request(
                api_token=True,
                api_token_owner=None,
                api_token_scopes=["chat"],
                current_user="api",
            )
        )

    assert exc.value.status_code == 403


def test_models_route_auth_disabled_keeps_cookie_owner_scoped(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    rows = [
        _ep(1, "alice-endpoint", "alice"),
        _ep(2, "shared-endpoint", None),
        _ep(3, "bob-endpoint", "bob"),
    ]

    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user="alice"),
    )

    assert _endpoint_names(endpoints) == ["alice-endpoint", "shared-endpoint"]


def test_models_route_auth_enabled_anonymous_returns_only_shared_rows(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    rows = [
        _ep(1, "alice-endpoint", "alice"),
        _ep(2, "shared-endpoint", None),
        _ep(3, "bob-endpoint", "bob"),
    ]
    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user=None),
    )

    assert _endpoint_names(endpoints) == ["shared-endpoint"]


def test_models_route_auth_disabled_returns_all_enabled_rows(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    rows = [
        _ep(1, "alice-endpoint", "alice"),
        _ep(2, "shared-endpoint", None),
        _ep(3, "bob-endpoint", "bob"),
    ]
    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user=None),
    )

    assert _endpoint_names(endpoints) == [
        "alice-endpoint",
        "shared-endpoint",
        "bob-endpoint",
    ]


def test_models_route_filters_hidden_models_and_secret_fields(monkeypatch):
    rows = [
        _ep(
            1,
            "alice-endpoint",
            "alice",
            base_url="https://alice.example/v1",
            cached_models=["visible-model", "hidden-model"],
            hidden_models=["hidden-model"],
            supports_tools=True,
            api_key="super-secret",
        ),
    ]

    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user="alice"),
    )

    assert endpoints == [{
        "endpoint_id": 1,
        "name": "alice-endpoint",
        "endpoint_url": "https://alice.example/v1/chat/completions",
        "models": ["visible-model"],
        "supports_tools": True,
    }]
    returned = endpoints[0]
    assert "hidden-model" not in returned["models"]
    assert set(returned) == {
        "endpoint_id",
        "name",
        "endpoint_url",
        "models",
        "supports_tools",
    }
    assert "api_key" not in returned
    assert "headers" not in returned
    assert "base_url" not in returned
    assert "super-secret" not in repr(returned)


def test_models_route_tolerates_invalid_cached_models_json(monkeypatch):
    endpoint = _ep(1, "alice-endpoint", "alice")
    endpoint.cached_models = "{not-json"
    rows = [endpoint]

    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user="alice"),
    )

    assert len(endpoints) == 1
    returned = endpoints[0]
    assert returned["name"] == "alice-endpoint"
    assert returned["models"] == []
    assert "api_key" not in returned
    assert "headers" not in returned
    assert "base_url" not in returned


def test_models_route_tolerates_invalid_hidden_models_json(monkeypatch):
    endpoint = _ep(
        1,
        "alice-endpoint",
        "alice",
        cached_models=["visible-model"],
    )
    endpoint.hidden_models = "{not-json"
    rows = [endpoint]

    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user="alice"),
    )

    assert len(endpoints) == 1
    returned = endpoints[0]
    assert returned["name"] == "alice-endpoint"
    assert returned["models"] == ["visible-model"]
    assert "api_key" not in returned
    assert "headers" not in returned
    assert "base_url" not in returned


def test_models_route_filters_disabled_and_non_llm_endpoints(monkeypatch):
    rows = [
        _ep(1, "enabled-llm", "alice", is_enabled=True, model_type="llm"),
        _ep(2, "legacy-null-type", "alice", is_enabled=True, model_type=None),
        _ep(3, "disabled-llm", "alice", is_enabled=False, model_type="llm"),
        _ep(4, "image-endpoint", "alice", is_enabled=True, model_type="image"),
    ]

    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user="alice"),
    )

    assert _endpoint_names(endpoints) == ["enabled-llm", "legacy-null-type"]


def test_models_route_returns_built_chat_url(monkeypatch):
    rows = [
        _ep(1, "alice-endpoint", "alice", base_url="https://raw.example/v1"),
    ]

    endpoints = _call_models_route(
        monkeypatch,
        rows,
        _request(api_token=False, current_user="alice"),
    )

    assert endpoints[0]["endpoint_url"] == "https://raw.example/v1/chat/completions"
    assert endpoints[0]["endpoint_url"] != "https://raw.example/v1"
