"""internal_api_base() resolution."""
import core.constants as cc
import src.constants as sc


def _base(monkeypatch, app_port=7011, **env):
    monkeypatch.delenv("ODYSSEUS_INTERNAL_BASE", raising=False)
    monkeypatch.setattr(sc, "APP_PORT", app_port)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return cc.internal_api_base()


def test_app_port_is_honored(monkeypatch):
    assert _base(monkeypatch, app_port=7860) == "http://127.0.0.1:7860"


def test_explicit_override_wins_and_is_stripped(monkeypatch):
    # Override beats APP_PORT and trailing slash is trimmed.
    assert _base(monkeypatch, app_port=7860,
                 ODYSSEUS_INTERNAL_BASE="https://proxy.example/") == "https://proxy.example"


def test_uses_127_not_localhost(monkeypatch):
    # 127.0.0.1 avoids IPv6/DNS ambiguity for the strictly-local loopback.
    assert "localhost" not in _base(monkeypatch)
