"""Pin matchModelKey (static/js/model/matchKey.js).

Regression: model name -> info/pricing lookups returned the FIRST substring
match, so "gpt-4o-mini" matched the shorter "gpt-4o" key and was billed at
gpt-4o rates (~16x) with the wrong context window.
"""
import json

from tests.helpers.node import run_node_module

_KEYS = ["gpt-4o", "gpt-4o-mini", "gpt-4", "o1", "o1-mini", "o1-pro", "o3", "o3-mini"]


def _match(names):
    return run_node_module(f"""
    import {{ matchModelKey }} from './static/js/model/matchKey.js';
    console.log(JSON.stringify({json.dumps(names)}.map(n => matchModelKey(n, {json.dumps(_KEYS)}))));
    """)


def test_prefers_longest_specific_key():
    assert _match(["gpt-4o-mini", "o1-mini", "o1-pro"]) == ["gpt-4o-mini", "o1-mini", "o1-pro"]


def test_base_model_and_unknown():
    assert _match(["gpt-4o-2024-08-06", "some-unknown-model"]) == ["gpt-4o", None]
