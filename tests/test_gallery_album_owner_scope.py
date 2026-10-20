"""Issue #2754: gallery albums are owner-scoped.

A caller cannot file an image into another user's album, and an album's count
covers only the caller's images.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.database as cdb
from core.database import GalleryAlbum, GalleryImage
import routes.gallery.gallery_routes as gallery_routes
from tests.helpers.database import disposable_database


def _seed(factory):
    db = factory()
    db.add_all([
        GalleryAlbum(id="album-alice", name="Alice album", owner="alice"),
        GalleryAlbum(id="album-bob", name="Bob album", owner="bob"),
        GalleryImage(id="img-alice", filename="a.png", owner="alice", album_id="album-alice", is_active=True),
        # A stray row from before the guard: bob's image filed in alice's album.
        GalleryImage(id="img-bob", filename="b.png", owner="bob", album_id="album-alice", is_active=True),
    ])
    db.commit()
    db.close()


def _client(monkeypatch, factory, user):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(gallery_routes, "get_current_user", lambda request: user)
    app = FastAPI()
    app.include_router(gallery_routes.setup_gallery_routes())
    return TestClient(app)


def _album_of(factory, image_id):
    db = factory()
    try:
        return db.get(GalleryImage, image_id).album_id
    finally:
        db.close()


def test_cannot_move_or_upload_into_another_users_album(monkeypatch, tmp_path):
    with disposable_database(tmp_path) as factory:
        _seed(factory)
        client = _client(monkeypatch, factory, "bob")

        assert client.patch("/api/gallery/img-bob", json={"album_id": "album-bob"}).status_code == 200
        assert client.patch("/api/gallery/img-bob", json={"album_id": "album-alice"}).status_code == 404
        assert _album_of(factory, "img-bob") == "album-bob"

        upload = client.post(
            "/api/gallery/upload",
            files={"file": ("x.png", b"not-a-png", "image/png")},
            data={"album_id": "album-alice"},
        )
        assert upload.status_code == 404


def test_album_count_covers_only_the_owners_images(monkeypatch, tmp_path):
    with disposable_database(tmp_path) as factory:
        _seed(factory)
        client = _client(monkeypatch, factory, "alice")

        albums = client.get("/api/gallery/albums").json()["albums"]
        assert [(a["id"], a["count"]) for a in albums] == [("album-alice", 1)]
