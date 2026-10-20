"""Regression guard for issue #6132 — the ChromaDB named volume was mounted at a
path the image never writes to, so the whole vector store lived in the
container's writable layer and was destroyed on every recreate. Silently: the
collection survived with a count of 0, and retrieval just stopped returning
anything.

``chromadb/chroma`` runs ``chroma run /config.yaml``, and that config is a single
line — ``persist_path: "/data"``. The image declares no ``VOLUME``, so nothing
outside a mount survives. ``/chroma/chroma`` is where pre-1.0 images kept the
store.

The documented backup procedure (website/backup-restore.md) archives the
``chromadb-data`` volume, so a wrong mount point also makes that tarball empty.

Pure YAML — no Docker required.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

COMPOSE = ROOT / "docker-compose.yml"

# `persist_path` from the image's own /config.yaml.
CHROMA_PERSIST_PATH = "/data"
LEGACY_PERSIST_PATH = "/chroma/chroma"
VOLUME_NAME = "chromadb-data"


def _chromadb_volumes(path: Path) -> list[str]:
    """Return a normalised list of ``source:target`` strings for the chromadb service.

    Docker Compose accepts volumes in two syntaxes:

    * Short-form string: ``"chromadb-data:/data"`` or ``"chromadb-data:/data:ro"``
    * Long-form mapping::

        - source: chromadb-data
          target: /data
          type: volume

    Both forms are normalised to ``"<source>:<target>"`` so that callers can
    use ``split(":")`` to extract either part without worrying about the original
    syntax or trailing mount-option fields (e.g. ``:z``, ``:ro``).
    """
    compose = yaml.safe_load(path.read_text(encoding="utf-8"))
    service = compose["services"]["chromadb"]
    raw = list(service.get("volumes") or [])
    result: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            # Long-form: normalise to "source:target" for uniform handling.
            source = entry.get("source", "")
            target = entry.get("target", "")
            result.append(f"{source}:{target}")
        else:
            # Short-form string: keep as-is; split(":")[1] is still the target
            # even when a third field (mount options like :z, :ro) is present.
            result.append(str(entry))
    return result


def test_chromadb_volume_is_mounted_at_the_persist_path():
    mounts = _chromadb_volumes(COMPOSE)
    targets = {m.split(":")[1] for m in mounts if m.startswith(f"{VOLUME_NAME}:")}
    assert targets, f"{COMPOSE.name}: no {VOLUME_NAME} mount on the chromadb service"
    assert targets == {CHROMA_PERSIST_PATH}, (
        f"{COMPOSE.name}: {VOLUME_NAME} is mounted at {sorted(targets)}, but the image "
        f"persists to {CHROMA_PERSIST_PATH!r}. Anything written outside a mount is "
        "lost when the container is recreated (issue #6132)."
    )


def test_chromadb_does_not_use_the_pre_1_0_path():
    """Verify that no mount places chromadb-data at the pre-1.0 store path.

    Uses ``split(":")[1]`` rather than ``endswith()`` so that mount-option
    suffixes (e.g. ``:z``, ``:ro``) do not mask a wrong target path.
    """
    mounts = _chromadb_volumes(COMPOSE)
    legacy = [m for m in mounts if ":" in m and m.split(":")[1] == LEGACY_PERSIST_PATH]
    assert not legacy, (
        f"{COMPOSE.name}: {LEGACY_PERSIST_PATH} is the pre-1.0 store location; "
        f"current images never write there. Offending entries: {legacy}"
    )


def test_chromadb_data_volume_is_declared():
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert VOLUME_NAME in (compose.get("volumes") or {}), (
        f"{COMPOSE.name}: the {VOLUME_NAME} volume is mounted but not declared"
    )
