import re
from unittest.mock import MagicMock, patch

import pytest

from services.memory.skill_importer import (
    ResolvedSource,
    SkillImportError,
    parse_skill_source,
)
from src.url_safety import check_outbound_url

## 1. Tests for Hostname Dispatch & Substring Spoofing

def test_parse_skill_source_rejects_unsupported_host_before_fetch():
    """Unsupported authorities must never reach the network unwrap path."""
    for url in (
        "https://skills.sh.attacker.com/owner/repo",
        "https://evilskills.sh/owner/repo",
        "https://notskills.sh/owner/repo",
        "https://api.skills.sh/owner/repo",
        "https://1.1.1.1/skills.sh/owner/repo",
        "http://localhost/skills.sh/owner/repo",
    ):
        with patch("services.memory.skill_importer._get_checked") as mock_get:
            with pytest.raises(SkillImportError):
                parse_skill_source(url)
        mock_get.assert_not_called()


def test_parse_skill_source_unwraps_skills_sh_redirect_to_github():
    """Both skills.sh spellings unwrap when the fetch lands on a GitHub host."""
    for entry in ("https://skills.sh/my-skill", "https://www.skills.sh/my-skill"):
        with patch("services.memory.skill_importer._get_checked") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.url = "https://github.com/test-owner/test-repo"
            mock_get.return_value = mock_response

            source = parse_skill_source(entry)
            assert source.owner == "test-owner"
            assert source.repo == "test-repo"


def test_parse_skill_source_rejects_skills_sh_page_that_never_reaches_github():
    """A skills.sh page that does not redirect to GitHub must fail loudly.

    The live site serves the skill page from ``www.skills.sh`` and only ever
    links the repository root, never the skill's subdirectory. Scraping a
    ``github.com`` link out of the body therefore resolves every skill in a
    repo to the same bundle, so the importer must refuse rather than guess.
    """
    body = '<html><body><a href="https://github.com/test-owner/test-repo">Repository</a></body></html>'
    with patch("services.memory.skill_importer._get_checked") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://www.skills.sh/anthropics/skills/pdf"
        mock_response.text = body
        mock_get.return_value = mock_response

        with pytest.raises(SkillImportError, match="did not redirect to GitHub"):
            parse_skill_source("https://skills.sh/anthropics/skills/pdf")


def test_parse_skill_source_reports_the_real_reason_for_rejection():
    """A supplied-but-unusable URL must not be reported as a missing URL."""
    for url, expected in (
        ("ftp://github.com/o/r", "unsupported URL scheme: ftp"),
        ("file:///etc/passwd", "unsupported URL scheme: file"),
        ("gopher://github.com/o/r", "unsupported URL scheme: gopher"),
        ("javascript:alert(1)", "Only GitHub or skills.sh URLs are supported"),
        ("mailto:x@y.z", "Only GitHub or skills.sh URLs are supported"),
        ("data:text/html,<b>x</b>", "Only GitHub or skills.sh URLs are supported"),
        ("https://evil.example/o/r", "Only GitHub or skills.sh URLs are supported"),
    ):
        with patch("services.memory.skill_importer._get_checked") as mock_get:
            with pytest.raises(SkillImportError, match=re.escape(expected)):
                parse_skill_source(url)
        mock_get.assert_not_called()


def test_parse_skill_source_accepts_schemeless_and_uppercase_github():
    """A schemeless host, an uppercase scheme, and a ``://`` in the query all parse."""
    for url, owner, repo in (
        ("github.com/octocat/Hello-World", "octocat", "Hello-World"),
        ("HTTPS://github.com/octocat/Hello-World", "octocat", "Hello-World"),
        ("github.com:443/octocat/Hello-World", "octocat", "Hello-World"),
        ("github.com/octocat/Hello-World?q=a://b", "octocat", "Hello-World"),
    ):
        source = parse_skill_source(url)
        assert (source.owner, source.repo) == (owner, repo)


def test_parse_skill_source_valid_github():
    """Ensure standard GitHub URLs parse into the correct ResolvedSource fields."""
    source = parse_skill_source("https://github.com/octocat/Hello-World/tree/main/docs")
    assert isinstance(source, ResolvedSource)
    assert source.owner == "octocat"
    assert source.repo == "Hello-World"
    assert source.ref == "main"
    assert source.path == "docs"


## 2. Tests for SSRF Guard & CGNAT

def test_check_outbound_url_blocks_cgnat():
    """Ensure Carrier-Grade NAT (RFC 6598) block 100.64.0.0/10 is blocked."""
    def mock_resolver(host):
        return ["100.64.5.10"]

    ok, reason = check_outbound_url("http://example.com", block_private=True, resolver=mock_resolver)
    assert not ok
    assert "private/shared/loopback" in reason  # Updated to match your codebase's error string

def test_check_outbound_url_blocks_loopback():
    """Ensure loopback IPs (127.0.0.1) are blocked by default."""
    def mock_resolver(host):
        return ["127.0.0.1"]

    ok, reason = check_outbound_url("http://localhost", block_private=True, resolver=mock_resolver)
    assert not ok


def test_check_outbound_url_blocks_metadata():
    """Ensure cloud metadata endpoints (169.254.169.254) are blocked."""
    def mock_resolver(host):
        return ["169.254.169.254"]

    ok, reason = check_outbound_url("http://metadata.google.internal", block_private=True, resolver=mock_resolver)
    assert not ok


def test_check_outbound_url_allows_public_ip():
    """Ensure public routable IPs pass successfully."""
    def mock_resolver(host):
        return ["93.184.216.34"]

    ok, reason = check_outbound_url("http://example.com", block_private=True, resolver=mock_resolver)
    assert ok
    assert reason == "ok"
