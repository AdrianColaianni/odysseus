"""Pin _matchesCombo (static/js/keyboard-shortcuts.js) against a non-string keybind.

Regression: keybinds are merged from the server response of
`/api/auth/settings` (`{ ..._defaultKeybinds, ...s.keybinds }`). A corrupt
or malformed `keybinds` value (e.g. a number instead of "ctrl+k") reached
`combo.split('+')` and threw "combo.split is not a function", breaking the
whole keydown handler. The guard treats any non-string combo as "no match".
"""
from tests.helpers.node import run_node_module


def test_non_string_combo_is_no_match_and_valid_combo_fires():
    results = run_node_module("""
    import { _matchesCombo } from './static/js/keyboard-shortcuts.js';
    const event = {key:'k',ctrlKey:false,altKey:false,shiftKey:false,metaKey:false};
    console.log(JSON.stringify([123, {}, null, 'k'].map(combo => _matchesCombo(event, combo))));
    """)
    assert results == [False, False, False, True]
