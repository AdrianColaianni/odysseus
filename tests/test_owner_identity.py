from types import SimpleNamespace

import pytest


def test_effective_storage_owner_matrix(monkeypatch):
    from src.owner_identity import DEFAULT_LOCAL_OWNER, effective_storage_owner

    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    assert effective_storage_owner(None) is None
    assert effective_storage_owner("") is None
    assert effective_storage_owner("alice") == "alice"
    for sentinel in ("api", "demo", "system", "internal-tool"):
        assert effective_storage_owner(sentinel) is None
        assert effective_storage_owner(f" {sentinel.upper()} ") is None

    monkeypatch.setenv("AUTH_ENABLED", "false")
    assert effective_storage_owner(None) == DEFAULT_LOCAL_OWNER
    assert effective_storage_owner("") == DEFAULT_LOCAL_OWNER
    assert effective_storage_owner("admin") == "admin"
    for sentinel in ("api", "demo", "system", "internal-tool"):
        assert effective_storage_owner(sentinel) is None


def test_auth_disabled_parser_is_centralized(monkeypatch):
    from src.owner_identity import auth_disabled

    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    assert auth_disabled() is False
    for value, expected in (("", False), ("0", False), ("true", False), (" FALSE ", True)):
        monkeypatch.setenv("AUTH_ENABLED", value)
        assert auth_disabled() is expected, value


def test_default_local_owner_is_reserved_auth_name_but_valid_storage_owner():
    from src.owner_identity import (
        DEFAULT_LOCAL_OWNER,
        REQUEST_SENTINEL_OWNERS,
        RESERVED_AUTH_USERNAMES,
        effective_storage_owner,
    )

    assert DEFAULT_LOCAL_OWNER in RESERVED_AUTH_USERNAMES
    assert DEFAULT_LOCAL_OWNER not in REQUEST_SENTINEL_OWNERS
    assert effective_storage_owner(DEFAULT_LOCAL_OWNER, auth_is_disabled=False) == DEFAULT_LOCAL_OWNER
    assert effective_storage_owner(DEFAULT_LOCAL_OWNER, auth_is_disabled=True) == DEFAULT_LOCAL_OWNER


def test_get_owned_or_404_hides_other_owners_and_gates_anonymous_on_request():
    from fastapi import HTTPException
    from src.auth_helpers import get_owned_or_404

    row = SimpleNamespace(owner="alice")
    db = SimpleNamespace(get=lambda model, row_id: row if row_id == "r1" else None)

    assert get_owned_or_404(db, object, "r1", "alice") is row
    assert get_owned_or_404(db, object, "r1", None) is row
    for row_id, owner, allow_anonymous in (("missing", "alice", True), ("r1", "bob", True), ("r1", None, False)):
        with pytest.raises(HTTPException) as exc:
            get_owned_or_404(db, object, row_id, owner, allow_anonymous=allow_anonymous)
        assert exc.value.status_code == 404
