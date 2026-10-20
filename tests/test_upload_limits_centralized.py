"""Centralized upload byte-limits (issue #3364).

Every per-route upload limit lives in ``src.upload_limits`` as a module-level
constant read through the validated ``read_byte_limit_env``. These tests pin:
- the default values (unchanged from the prior per-route literals),
- env-overridability for each one, and
- that an invalid env value fails fast (validation).
"""

import importlib

import pytest

import src.upload_limits as upload_limits

# const name -> (env var, default bytes)
_LIMITS = {
    "GALLERY_UPLOAD_MAX_BYTES": ("ODYSSEUS_GALLERY_UPLOAD_MAX_BYTES", 100 * 1024 * 1024),
    "GALLERY_TRANSFORM_UPLOAD_MAX_BYTES": ("ODYSSEUS_GALLERY_TRANSFORM_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "MEMORY_IMPORT_MAX_BYTES": ("ODYSSEUS_MEMORY_IMPORT_MAX_BYTES", 10 * 1024 * 1024),
    "PERSONAL_UPLOAD_MAX_BYTES": ("ODYSSEUS_PERSONAL_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "EMAIL_COMPOSE_UPLOAD_MAX_BYTES": ("ODYSSEUS_EMAIL_COMPOSE_UPLOAD_MAX_BYTES", 25 * 1024 * 1024),
    "STT_MAX_AUDIO_BYTES": ("ODYSSEUS_STT_MAX_AUDIO_BYTES", 25 * 1024 * 1024),
    "ICS_MAX_BYTES": ("ODYSSEUS_ICS_MAX_BYTES", 10 * 1024 * 1024),
}


def _reload_clean(monkeypatch):
    """Reload upload_limits with all the limit env vars unset."""
    for env, _ in _LIMITS.values():
        monkeypatch.delenv(env, raising=False)
    return importlib.reload(upload_limits)


@pytest.fixture(autouse=True)
def _restore_module():
    # Ensure later tests see the env-default module, not a test-mutated reload.
    yield
    importlib.reload(upload_limits)


def test_default_values(monkeypatch):
    mod = _reload_clean(monkeypatch)
    for name, (_env, default) in _LIMITS.items():
        assert getattr(mod, name) == default, name


def test_each_limit_reads_its_own_env_var(monkeypatch):
    for name, (env, _default) in _LIMITS.items():
        _reload_clean(monkeypatch)
        monkeypatch.setenv(env, "4242")
        mod = importlib.reload(upload_limits)
        assert getattr(mod, name) == 4242, name


def test_invalid_env_fails_fast(monkeypatch):
    _reload_clean(monkeypatch)
    monkeypatch.setenv("ODYSSEUS_ICS_MAX_BYTES", "not-an-int")
    with pytest.raises(ValueError, match="ODYSSEUS_ICS_MAX_BYTES"):
        importlib.reload(upload_limits)


def test_non_positive_env_rejected(monkeypatch):
    _reload_clean(monkeypatch)
    monkeypatch.setenv("ODYSSEUS_ICS_MAX_BYTES", "0")
    with pytest.raises(ValueError, match="greater than 0"):
        importlib.reload(upload_limits)
