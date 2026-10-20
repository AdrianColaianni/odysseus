"""Regression: the Qwen bare-marker scrub must not eat a lone `end` (#5547).

`_QWEN_BARE_MARKER_RE` cleans Qwen turn markers that leak into content. Its
`end` branch was `\\|?end\\|?`, both pipes optional, so it also matched a bare
`end` surrounded by whitespace and replaced it with a space. Any message
containing Ruby, Lua or shell code that closes a block with a lone `end` had
those lines silently deleted, in the stored text and in the rendered message.

Requiring at least one pipe keeps every real marker (`|end`, `end|`, `|end|`,
`/|end|`) stripping as before. The same pattern is duplicated in
static/js/chatRenderer.js, so the JS copy is checked here too; the two must
not drift.
"""
import json
import re
from pathlib import Path

import src.agent_tools  # noqa: F401  (break agent_tools<->tool_parsing import cycle)
from src.tool_parsing import strip_tool_blocks
from tests.helpers.node import run_node_module

_CHAT_RENDERER = Path(__file__).resolve().parent.parent / "static" / "js" / "chatRenderer.js"

# Inputs that must survive untouched, and the substring that proves they did.
KEPT = [
    ("loop do\n    puts \"yo\"\nend\n", "\nend"),          # the reported Ruby case
    ("a end b", "a end b"),
    ("END", "END"),
    ("x assistant y", "x assistant y"),          # mid-sentence must survive (#5971)
]

# Real markers, at least one pipe plus the role word, with the exact output
# they must still produce. Asserted as equality rather than "marker not in out"
# so narrowing the pattern can't pass by deleting more than it should.
STRIPPED = [
    ("a |end| b", "a  b"),
    ("a /|end| b", "a  b"),
    ("a |end b", "a  b"),
    ("a end| b", "a  b"),
    ("Before\nassistant\nAfter", "Before \nAfter"),   # bare-marker on its own line still stripped
    ("Before\n\tassistan  \nAfter", "Before \nAfter"),       # truncated marker variant still stripped
]


def test_bare_end_survives_stripping():
    for text, kept in KEPT:
        assert kept in strip_tool_blocks(text), text


def test_piped_end_markers_are_still_stripped():
    for text, expected in STRIPPED:
        assert strip_tool_blocks(text) == expected, text


def test_bare_end_inside_a_fenced_block_survives():
    """The scrub runs over the whole message, fenced regions included."""
    out = strip_tool_blocks("Here:\n```ruby\nloop do\n  puts 1\nend\n```\nDone.")
    assert "\nend\n" in out


def _js_bare_marker_regex_source():
    src = _CHAT_RENDERER.read_text(encoding="utf-8")
    m = re.search(r"^const QWEN_BARE_MARKER_RE = (/.*/[gimsuy]*);$", src, re.MULTILINE)
    assert m, "QWEN_BARE_MARKER_RE literal not found in chatRenderer.js"
    return m.group(1)


def test_js_copy_of_the_pattern_matches_the_python_one():
    """Guard the duplication: the JS branch must require a pipe too."""
    cases = [text for text, _ in KEPT] + [text for text, _ in STRIPPED]
    got = run_node_module(
        f"const RE = {_js_bare_marker_regex_source()};\n"
        f"const cases = {json.dumps(cases)};\n"
        "console.log(JSON.stringify(cases.map(c => c.replace(RE, ' '))));"
    )

    for (text, kept), out in zip(KEPT, got):
        assert kept in out, f"JS regex dropped {kept!r} from {text!r}"
    for (text, expected), out in zip(STRIPPED, got[len(KEPT):]):
        assert out == expected, f"JS regex: {text!r} -> {out!r}, expected {expected!r}"
