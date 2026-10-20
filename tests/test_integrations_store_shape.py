import json
import asyncio
from types import SimpleNamespace

import pytest

from src import integrations
from tests.helpers.routes import route_endpoint


def test_load_integrations_skips_non_object_rows(tmp_path, monkeypatch):
    data_file = tmp_path / "integrations.json"
    data_file.write_text(json.dumps([{"id": "good", "name": "Good"}, "bad", None]))
    monkeypatch.setattr(integrations, "DATA_FILE", str(data_file))

    assert integrations.load_integrations() == [{"id": "good", "name": "Good"}]


@pytest.fixture
def integrations_routes(tmp_path, monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from routes import auth_routes

    monkeypatch.setattr(integrations, "DATA_FILE", str(tmp_path / "integrations.json"))
    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)

    class _AuthManager:
        def get_username_for_token(self, token):
            return "admin" if token == "session-token" else None

        def is_admin(self, user):
            return user == "admin"

    router = auth_routes.setup_auth_routes(_AuthManager())
    return router, auth_routes.SESSION_COOKIE, fastapi.HTTPException


class _JsonRequest(SimpleNamespace):
    def __init__(self, body, session_cookie):
        super().__init__(
            cookies={session_cookie: "session-token"},
            client=SimpleNamespace(host="127.0.0.1"),
            _body=body,
        )

    async def json(self):
        return self._body


INVALID_FIELDS = [
    {"name": "   "},
    {"base_url": ""},
    {"base_url": "ftp://example.test"},
    {"base_url": "https://example.test/api?token=abc"},
]


def test_create_integration_rejects_invalid_fields_without_persisting(integrations_routes):
    router, session_cookie, http_exception = integrations_routes
    create_integration = route_endpoint(router, "/api/auth/integrations", "POST")

    for invalid in INVALID_FIELDS:
        body = {"name": "Example", "base_url": "https://example.test", **invalid}
        with pytest.raises(http_exception) as exc:
            asyncio.run(create_integration(_JsonRequest(body, session_cookie)))
        assert exc.value.status_code == 400, invalid
    assert integrations.load_integrations() == []


def test_update_integration_rejects_invalid_fields_without_changing_existing(integrations_routes):
    router, session_cookie, http_exception = integrations_routes
    update_integration = route_endpoint(router, "/api/auth/integrations/{integration_id}", "PUT")
    existing = {"id": "existing", "name": "Original", "base_url": "https://example.test"}
    integrations.save_integrations([existing])

    for invalid in INVALID_FIELDS:
        with pytest.raises(http_exception) as exc:
            asyncio.run(update_integration(
                integration_id="existing",
                request=_JsonRequest(invalid, session_cookie),
            ))
        assert exc.value.status_code == 400, invalid
    assert integrations.load_integrations() == [existing]
