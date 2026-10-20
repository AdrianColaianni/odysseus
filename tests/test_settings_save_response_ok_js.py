"""Frontend regression tests: verify settings save handlers check HTTP response status.

Locks in that static/js/settings.js verifies response.ok before displaying success,
preventing 401, 403, 400, and 500 responses from reporting false success.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SETTINGS_JS = _REPO / "static" / "js" / "settings.js"
_SETTINGS_DIR = _REPO / "static" / "js" / "settings"
_SETTINGS_API_JS = _SETTINGS_DIR / "api.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_settings_js_syntax():
    """Verify static/js/settings.js and settings/*.js modules are syntactically valid JavaScript."""
    js_files = [_SETTINGS_JS] + list(_SETTINGS_DIR.glob("*.js"))
    for js_file in js_files:
        proc = subprocess.run(
            ["node", "--check", str(js_file)],
            capture_output=True,
            text=True,
            cwd=str(_REPO),
        )
        assert proc.returncode == 0, f"JS syntax error in {js_file.name}:\n{proc.stderr}"


def test_post_settings_helper_verifies_response_ok():
    """Centralized postSettings in settings/api.js must verify response.ok and throw on failure."""
    assert _SETTINGS_API_JS.exists(), f"Expected {_SETTINGS_API_JS} to exist"
    api_content = _SETTINGS_API_JS.read_text(encoding="utf-8")

    # Verify fetch to /api/auth/settings with POST method
    match = re.search(r"fetch\(['\"]/api/auth/settings['\"],\s*\{\s*method:\s*['\"]POST['\"]", api_content)
    assert match is not None, "Expected POST fetch to /api/auth/settings in settings/api.js"

    # Verify .ok is checked within 300 characters of fetch
    window = api_content[match.start(): match.start() + 300]
    assert ".ok" in window, f"postSettings must check response.ok:\n{window}"

    # Verify that it throws an error when !response.ok
    assert "throw error" in api_content or "throw new Error" in api_content, (
        "postSettings must throw when response is not ok"
    )
