"""Pin the pure hexToRgb helper (static/js/color/hex.js).

Regression: theme.js parsed hex with fixed substring(0,2)/(2,4)/(4,6) slices, so
a 3-digit shorthand like "#abc" produced NaN channels (the color picker already
expanded shorthand correctly — theme parsing did not).
"""
import json
from pathlib import Path

from tests.helpers.node import run_node_module

_HELPER = Path(__file__).resolve().parent.parent / "static" / "js" / "color" / "hex.js"


def _rgb(hex_str: str):
    js = (
        f"import {{ hexToRgb }} from '{_HELPER.as_posix()}';"
        f"console.log(JSON.stringify(hexToRgb({json.dumps(hex_str)})));"
    )
    return run_node_module(js)


def test_shorthand_expands():
    assert _rgb("#abc") == {"r": 0xAA, "g": 0xBB, "b": 0xCC}


def test_full_form_and_no_hash():
    assert _rgb("#ff8800") == {"r": 255, "g": 136, "b": 0}
    assert _rgb("ff8800") == {"r": 255, "g": 136, "b": 0}


def test_invalid_returns_null():
    assert _rgb("nothex") is None
    assert _rgb("") is None
