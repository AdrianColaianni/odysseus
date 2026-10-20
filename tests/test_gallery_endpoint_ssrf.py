"""The gallery image-edit proxies must never fetch a client-supplied ``_endpoint``.

``POST /api/image/harmonize`` and ``POST /api/image/inpaint`` take an
``_endpoint`` in the body. It must pass the outbound URL check and match a
registered endpoint, so a caller cannot aim the server at cloud metadata or an
unregistered host.
"""
import asyncio

import httpx
import pytest
from fastapi import HTTPException

import routes.gallery.gallery_routes as gallery
from tests.helpers.routes import route_endpoint


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return dict(self._body)


class _Db:
    def close(self):
        pass


@pytest.fixture
def proxies(monkeypatch):
    monkeypatch.setattr(gallery, "require_privilege", lambda *args: "alice")
    monkeypatch.setattr(gallery, "SessionLocal", _Db)

    def no_outbound(**kwargs):
        raise AssertionError("outbound request made for a rejected endpoint")

    monkeypatch.setattr(httpx, "AsyncClient", no_outbound)
    router = gallery.setup_gallery_routes()
    return [
        route_endpoint(router, "/api/image/inpaint", "POST"),
        route_endpoint(router, "/api/image/harmonize", "POST"),
    ]


def _status(endpoint, base):
    body = {"_endpoint": base, "_model": "m", "image": "aGk=", "mask": "aGk=", "prompt": "p"}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(endpoint(_Request(body)))
    return exc.value.status_code


def test_proxies_reject_metadata_endpoint_before_any_fetch(proxies):
    for endpoint in proxies:
        assert _status(endpoint, "http://169.254.169.254/latest/meta-data") == 400


def test_proxies_reject_unregistered_endpoint(proxies, monkeypatch):
    monkeypatch.setattr("src.url_safety.check_outbound_url", lambda *args, **kwargs: (True, ""))
    monkeypatch.setattr(gallery, "_visible_image_endpoint_for_base", lambda *args: None)
    for endpoint in proxies:
        assert _status(endpoint, "https://unregistered.test/v1") == 403
