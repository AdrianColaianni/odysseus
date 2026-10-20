import os

import pytest
from fastapi import HTTPException


def _generated_images_module():
    from src import generated_images
    return generated_images


def test_generated_image_path_allows_safe_existing_file(tmp_path, monkeypatch):
    generated_images = _generated_images_module()
    image_dir = tmp_path / "generated_images"
    image_dir.mkdir()
    filename = "a" * 12 + ".png"
    image_path = image_dir / filename
    image_path.write_bytes(b"png")
    monkeypatch.setattr(generated_images, "GENERATED_IMAGE_DIR", image_dir)

    assert generated_images.resolve_generated_image_path(filename) == image_path


def test_generated_image_path_rejects_invalid_filenames(tmp_path, monkeypatch):
    generated_images = _generated_images_module()
    image_dir = tmp_path / "generated_images"
    image_dir.mkdir()
    monkeypatch.setattr(generated_images, "GENERATED_IMAGE_DIR", image_dir)

    for filename in ("../../secret.png", "zzzzzzzz.png", None):
        with pytest.raises(HTTPException) as exc:
            generated_images.resolve_generated_image_path(filename)
        assert exc.value.status_code == 400, filename


def test_generated_image_path_rejects_symlink_escape(tmp_path, monkeypatch):
    generated_images = _generated_images_module()
    image_dir = tmp_path / "generated_images"
    image_dir.mkdir()
    filename = "b" * 12 + ".png"
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside image root")
    try:
        os.symlink(outside, image_dir / filename)
    except (AttributeError, NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    monkeypatch.setattr(generated_images, "GENERATED_IMAGE_DIR", image_dir)

    with pytest.raises(HTTPException) as exc:
        generated_images.resolve_generated_image_path(filename)

    assert exc.value.status_code == 400

