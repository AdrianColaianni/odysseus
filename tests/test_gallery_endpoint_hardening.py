"""Focused security tests for gallery endpoint URL hardening.

Covers:
- _is_openai_api_base: exact hostname matching (no substring bypass)
- _join_checked_gallery_endpoint: allowlist-only path construction
- No bare str(e) / f"...{e}" in gallery exception handlers
- harmonize candidate paths stay inside the allowlist
"""
import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "routes" / "gallery" / "gallery_routes.py"

import routes.gallery.gallery_routes as gallery_routes


# ---------------------------------------------------------------------------
# _is_openai_api_base — exact hostname, no substring tricks
# ---------------------------------------------------------------------------

def test_is_openai_api_base_accepts_exact_host():
    f = gallery_routes._is_openai_api_base
    assert f("https://api.openai.com") is True
    assert f("https://api.openai.com/v1") is True
    assert f("https://api.openai.com/") is True
    assert f("api.openai.com") is True


def test_is_openai_api_base_rejects_path_embed():
    # attacker hides api.openai.com in the path, not the hostname
    f = gallery_routes._is_openai_api_base
    assert f("https://evil.test/api.openai.com/v1") is False


def test_is_openai_api_base_rejects_subdomain_suffix():
    # hostname ends with .openai.com but isn't exactly api.openai.com
    f = gallery_routes._is_openai_api_base
    assert f("https://api.openai.com.evil.test/v1") is False
    assert f("https://evil-api.openai.com/v1") is False
    assert f("https://notapi.openai.com/v1") is False


def test_is_openai_api_base_rejects_malformed():
    f = gallery_routes._is_openai_api_base
    assert f("") is False
    assert f("not a url at all !!!") is False


# ---------------------------------------------------------------------------
# _join_checked_gallery_endpoint — allowlist enforcement
# ---------------------------------------------------------------------------

def test_join_checked_accepts_known_paths():
    j = gallery_routes._join_checked_gallery_endpoint
    assert j("http://localhost:7860/v1", "/images/img2img") == "http://localhost:7860/v1/images/img2img"
    assert j("http://localhost:7860", "/sdapi/v1/img2img") == "http://localhost:7860/sdapi/v1/img2img"
    assert j("https://api.openai.com/v1", "/images/edits") == "https://api.openai.com/v1/images/edits"


def test_join_checked_rejects_unknown_path():
    import pytest
    j = gallery_routes._join_checked_gallery_endpoint
    with pytest.raises(ValueError):
        j("http://localhost/v1", "/arbitrary/user/path")
    with pytest.raises(ValueError):
        j("http://localhost/v1", "")
    with pytest.raises(ValueError):
        j("http://localhost/v1", "https://evil.test/steal")


# ---------------------------------------------------------------------------
# Source-level: no raw str(e) / f"...{e}" returned to API clients
# ---------------------------------------------------------------------------

def test_no_raw_exception_string_in_client_responses():
    src = SRC.read_text()
    # Patterns that indicate exception internals flowing into client-visible values.
    # We allow them only in logger calls (checked separately below).
    bad_patterns = [
        r'return \{"error": str\(e\)\}',
        r'return \{"error": f"[^"]*\{e\}[^"]*"\}',
        r'HTTPException\(\d+, str\(e\)\)',
        r'HTTPException\(\d+, f"[^"]*\{e\}[^"]*"\)',
    ]
    for pattern in bad_patterns:
        matches = re.findall(pattern, src)
        assert not matches, (
            f"Pattern {pattern!r} matched — raw exception string returned to client: {matches}"
        )


def _function_source(src_text: str, func_name: str) -> str:
    tree = ast.parse(src_text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(src_text, node) or ""
    raise AssertionError(f"{func_name} not found in {SRC}")


def test_gallery_endpoint_paths_allowlist_covers_all_harmonize_candidates():
    # Every path in the candidates list must be in the pre-approved allowlist.
    src = SRC.read_text()
    body = _function_source(src, "harmonize_image")
    # Extract string literals that look like route paths from candidates
    candidate_paths = re.findall(r'"/(?:images|sdapi)/[^"]*"', body)
    allowed = gallery_routes._GALLERY_ENDPOINT_PATHS
    for p in candidate_paths:
        p = p.strip('"')
        assert p in allowed, (
            f"Path {p!r} used in harmonize candidates but not in _GALLERY_ENDPOINT_PATHS allowlist"
        )


# ---------------------------------------------------------------------------
# _is_openai_api_base — userinfo bypass
# ---------------------------------------------------------------------------

def test_is_openai_api_base_rejects_userinfo_bypass():
    # userinfo trick: user = api.openai.com, host = evil.test
    f = gallery_routes._is_openai_api_base
    assert f("https://api.openai.com@evil.test/v1") is False


# ---------------------------------------------------------------------------
# Source-level: no client-visible error leaks upstream body fragments
# ---------------------------------------------------------------------------

def _extract_httpexception_call(src: str, pos: int) -> str:
    """Paren-match from the opening '(' of an HTTPException call."""
    start = src.index("(", pos)
    depth = 0
    for k, ch in enumerate(src[start:]):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[start : start + k + 1]
    return src[start:]


def test_no_upstream_data_in_client_responses():
    """No raise HTTPException or return {"error": ...} may expose upstream body data."""
    src = SRC.read_text()
    forbidden = [
        "r.text",
        "body[:",
        'data["error"]',
        "data['error']",
        "last_err",
        "{base}",
    ]

    for m in re.finditer(r"\braise\s+HTTPException\s*\(", src):
        line_start = src.rfind("\n", 0, m.start()) + 1
        if "logger." in src[line_start : m.start()]:
            continue
        call_text = _extract_httpexception_call(src, m.start())
        for frag in forbidden:
            assert frag not in call_text, (
                f"HTTPException raise at byte {m.start()} exposes {frag!r} to client:\n{call_text[:300]}"
            )

    for m in re.finditer(r'return\s*\{"error":', src):
        line_end = src.find("\n", m.start())
        line = src[m.start() : line_end if line_end != -1 else len(src)]
        for frag in forbidden:
            assert frag not in line, (
                f"Error return at byte {m.start()} exposes {frag!r} to client:\n{line}"
            )
