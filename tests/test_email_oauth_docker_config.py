"""Regression coverage for Google OAuth configuration in Docker Compose."""

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parent.parent
COMPOSE_PATHS = tuple(
    ROOT / name
    for name in (
        "docker-compose.yml",
    )
)
ENV_EXAMPLE_PATH = ROOT / ".env.example"


def _env_example():
    if not ENV_EXAMPLE_PATH.exists():
        pytest.skip("this checkout does not include the optional .env.example file")
    return ENV_EXAMPLE_PATH.read_text(encoding="utf-8")


def _odysseus_environment(path):
    compose = yaml.safe_load(path.read_text(encoding="utf-8"))
    return set(compose["services"]["odysseus"]["environment"])


def test_google_oauth_settings_are_forwarded():
    for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI"):
        expected = f"{key}=${{{key}:-}}"
        for path in COMPOSE_PATHS:
            assert expected in _odysseus_environment(path), path.name


def test_env_example_holds_no_real_google_client_secret():
    env_example = _env_example()
    assert "GOCSPX-" not in env_example
