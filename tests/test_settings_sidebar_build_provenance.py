"""The settings sidebar footer that names the running build.

``formatSettingsBuildInfo`` decides what the footer says, including what to do
with the ``"unknown"`` the backend reports when it cannot resolve a commit.
"""

import json

from tests.helpers.node import run_node_module


def _format_build_info(payload):
    """Run the shipped formatter over one payload and return its result."""
    return run_node_module(
        "import { formatSettingsBuildInfo } from './static/js/settings/sidebar.js';\n"
        f"console.log(JSON.stringify(formatSettingsBuildInfo({json.dumps(payload)})));\n"
    )


def test_shows_registered_version_and_short_commit():
    info = _format_build_info(
        {
            "version": "1.0.3",
            "build": "0.20.19",
            "source_commit": "8a28c5f9c0ffee1234567890abcdef1234567890",
        }
    )

    assert info["versionLabel"] == "v1.0.3 · build 0.20.19"
    assert info["commitLabel"] == "8a28c5f9"
    # The short hash is what fits the sidebar; the full one stays on hover.
    assert info["commitTitle"] == "8a28c5f9c0ffee1234567890abcdef1234567890"


def test_build_equal_to_version_is_not_printed_twice():
    info = _format_build_info(
        {"version": "1.0.3", "build": "1.0.3", "source_commit": "abcdef1234"}
    )

    assert info["versionLabel"] == "v1.0.3"


def test_unresolvable_commit_leaves_only_the_version():
    """`/api/version` reports the string "unknown" when `git rev-parse` fails
    — a read-only Docker tree with no `.git`. Printing it would be worse than
    printing nothing."""
    info = _format_build_info(
        {"version": "1.0.3", "build": "unknown", "source_commit": "unknown"}
    )

    assert info["versionLabel"] == "v1.0.3"
    assert info["commitLabel"] == ""
    assert info["commitTitle"] == ""


def test_commit_only_build_still_gets_a_footer():
    info = _format_build_info({"source_commit": "0123456789abcdef"})

    assert info["versionLabel"] == ""
    assert info["commitLabel"] == "01234567"


def test_non_sha_commit_override_is_left_intact():
    """`ODYSSEUS_SOURCE_COMMIT` can be any string; truncating a tag to eight
    characters would corrupt it, so only real hashes get shortened."""
    info = _format_build_info(
        {"version": "1.0.3", "source_commit": "release-2026-09-30"}
    )

    assert info["commitLabel"] == "release-2026-09-30"


def test_nothing_to_report_means_no_footer():
    for payload in (
        {},
        {"version": "unknown", "build": "unknown", "source_commit": "unknown"},
    ):
        assert _format_build_info(payload) is None, payload


def test_api_version_reports_version_build_and_commit():
    """The footer renders these three keys. `/api/version` is auth-exempt, so
    it answers without a session — the same way the login page already reads
    it."""
    from fastapi.testclient import TestClient

    from app import app

    with TestClient(app) as client:
        payload = client.get("/api/version").json()

    assert set(payload) >= {"version", "build", "source_commit"}
    # Absent values are reported as "unknown", never omitted or null, which is
    # the case formatSettingsBuildInfo() filters on.
    assert all(isinstance(payload[k], str) and payload[k] for k in payload)
