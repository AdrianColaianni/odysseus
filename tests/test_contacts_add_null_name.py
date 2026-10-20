"""Regression: POST /api/contacts/add must not crash when name/email is JSON null.

The handler did `data.get("name", "").strip()`. dict.get returns the default
only when the key is ABSENT; a body like {"name": null, "email": "x@y.com"}
gives name=None, so None.strip() raised AttributeError -> 500. Now guarded with
`(data.get("name") or "")`.
"""
import asyncio

import pytest
from starlette.requests import Request

import routes.contacts.contacts_routes as cr
from tests.helpers.routes import route_endpoint


def _add_handler():
    return route_endpoint(cr.setup_contacts_routes(), "/api/contacts/add", "POST")


def _request():
    request = Request({"type": "http", "method": "POST", "path": "/api/contacts/add", "headers": []})
    request.state.current_user = "admin"
    return request


@pytest.fixture
def _stub_store(monkeypatch):
    created = []
    monkeypatch.setattr(cr, "_fetch_contacts", lambda *a, **k: [])
    monkeypatch.setattr(
        cr,
        "_create_contact",
        lambda name, email="", address="", phones=None: created.append((name, email, address, phones or [])) or True,
    )
    return created


def test_null_name_does_not_crash(_stub_store):
    handler = _add_handler()
    result = asyncio.run(handler({"name": None, "email": "x@y.com"}, _request()))
    assert result["success"] is True
    # name fell back to the email local-part instead of crashing.
    assert _stub_store == [("x", "x@y.com", "", [])]


def test_null_email_does_not_crash(_stub_store):
    handler = _add_handler()
    result = asyncio.run(handler({"name": "Bob", "email": None}, _request()))
    assert result["success"] is True
    assert _stub_store == [("Bob", "", "", [])]


def test_phone_only_contact_is_allowed(_stub_store):
    handler = _add_handler()
    result = asyncio.run(handler({"name": "Bob", "email": None, "phone": "0805412 7841"}, _request()))
    assert result["success"] is True
    assert _stub_store == [("Bob", "", "", ["0805412 7841"])]
