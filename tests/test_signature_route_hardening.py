import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from routes import signature_routes
from tests.helpers.routes import route_endpoint


_PNG_BYTES = b"\x89PNG\r\n\x1a\nsignature-bytes"
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode("ascii")


class _SignatureRecord:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.created_at = None


class _FakeDb:
    def __init__(self):
        self.added = None
        self.add = MagicMock(side_effect=self._add)
        self.commit = MagicMock()
        self.refresh = MagicMock()
        self.rollback = MagicMock()
        self.close = MagicMock()

    def _add(self, sig):
        self.added = sig


def _request(user="alice"):
    return SimpleNamespace(state=SimpleNamespace(current_user=user))


def _route_endpoint(path, method):
    return route_endpoint(signature_routes.setup_signature_routes(), path, method)


def test_signature_png_normalization_accepts_data_url_and_raw_base64():
    data_url = f"data:image/png;base64,{_PNG_B64}"

    assert signature_routes._normalize_signature_png(data_url) == _PNG_B64
    assert signature_routes._normalize_signature_png(_PNG_B64) == _PNG_B64


def test_signature_png_normalization_rejects_invalid_inputs():
    for raw in (
        "",
        "not base64!!!",
        base64.b64encode(b"not a png").decode("ascii"),
        "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8jpeg").decode("ascii"),
        "A" * (signature_routes._MAX_SIGNATURE_B64 + 4),
    ):
        with pytest.raises(HTTPException) as exc:
            signature_routes._normalize_signature_png(raw)

        assert exc.value.status_code == 400


def test_signature_dimensions_are_bounded():
    for value in (0, -1, signature_routes._MAX_SIGNATURE_DIMENSION + 1, "20"):
        with pytest.raises(HTTPException) as exc:
            signature_routes._signature_dimension(value)

        assert exc.value.status_code == 400


def test_create_signature_stores_normalized_png_and_drops_svg(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(signature_routes, "Signature", _SignatureRecord)
    create_signature = _route_endpoint("/api/signatures", "POST")

    response = create_signature(
        _request(),
        signature_routes.SignatureCreate(
            name=" Full signature ",
            data=f"data:image/png;base64,{_PNG_B64}",
            width=320,
            height=80,
            svg='<svg onload="alert(1)"></svg>',
        ),
        db=db,
    )

    assert db.added.owner == "alice"
    assert db.added.name == "Full signature"
    assert db.added.data_png == _PNG_B64
    assert db.added.width == 320
    assert db.added.height == 80
    assert db.added.svg is None
    assert response["data_url"] == f"data:image/png;base64,{_PNG_B64}"
    db.commit.assert_called_once()
