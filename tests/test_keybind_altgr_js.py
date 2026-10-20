"""Pin the AltGr-safety of the shared keybind predicate and the matcher.

Bug: browsers report the AltGr key (right Alt, essential on AZERTY/QWERTZ and
many non-US layouts to type @ # { } [ ] | \\ and €) as ctrlKey=true AND
altKey=true, so a user on a non-US layout typing a special character could
silently fire a destructive ctrl+alt+<letter> default (new_session,
delete_session, incognito, open_calendar). getModifierState('AltGraph') is true
for AltGr but false for a genuine left Ctrl+Alt — except on macOS, where the
Option key also sets it.

The guard now lives in ONE place — `isAltGrEvent` in static/js/platform.js — and
all three call sites (editor keyboard-shortcuts.js, root keyboard-shortcuts.js,
settings.js) route through it. So these tests pin the shared *predicate*
directly (both the isMac arg and the navigator-derived IS_MAC default), plus the
`_matchesCombo` integration. They do NOT prove that real browsers actually set
AltGraph for AltGr — that mapping is taken from the UI Events spec / MDN; older
Firefox and some Linux setups historically did not report it (the guard is a
no-op there, i.e. pre-fix behaviour, not a regression).
"""
import json
from pathlib import Path

from tests.helpers.node import run_node_module

_REPO = Path(__file__).resolve().parent.parent
_HELPER = _REPO / "static" / "js" / "keyboard-shortcuts.js"
_PLATFORM = _REPO / "static" / "js" / "platform.js"


def _is_altgr(
    altgraph: bool,
    is_mac: bool = False,
    has_modifier_state: bool = True,
    ctrl: bool = True,
    alt: bool = True,
) -> bool:
    """Return isAltGrEvent(ev, is_mac) — the predicate every guard routes through."""
    modifier = (
        f"ev.getModifierState = (m) => m === 'AltGraph' ? {json.dumps(altgraph)} : false;"
        if has_modifier_state else "")
    js = f"""
    import {{ isAltGrEvent }} from '{_PLATFORM.as_uri()}';
    const ev = {{ ctrlKey: {json.dumps(ctrl)}, altKey: {json.dumps(alt)} }};
    {modifier}
    console.log(JSON.stringify(isAltGrEvent(ev, {json.dumps(is_mac)})));
    """
    return run_node_module(js)


def _is_mac_default(platform: str = "", user_agent: str = "") -> bool:
    """Return platform.js IS_MAC as derived from a stubbed navigator at import time."""
    # Node >=21 exposes a read-only global `navigator`, so assignment throws;
    # defineProperty (configurable) overrides it for the import-time read.
    js = f"""
    Object.defineProperty(globalThis, 'navigator', {{
      value: {{ platform: {json.dumps(platform)}, userAgent: {json.dumps(user_agent)} }},
      configurable: true,
    }});
    const {{ IS_MAC }} = await import('{_PLATFORM.as_uri()}');
    console.log(JSON.stringify(IS_MAC));
    """
    return run_node_module(js)


def _matches(event: dict, combo: str, altgraph: bool, is_mac: bool = False) -> bool:
    """Return _matchesCombo(event, combo, is_mac) with AltGraph active or not."""
    js = f"""
    import {{ _matchesCombo }} from '{_HELPER.as_uri()}';
    const ev = {json.dumps(event)};
    ev.getModifierState = (m) => m === 'AltGraph' ? {json.dumps(altgraph)} : false;
    console.log(JSON.stringify(_matchesCombo(ev, {json.dumps(combo)}, {json.dumps(is_mac)})));
    """
    return run_node_module(js)


# --- The shared predicate (covers all three guards) --------------------------

def test_isaltgr_true_for_altgr_keystroke_off_mac():
    # AZERTY/QWERTZ user holds AltGr: browser sets ctrlKey+altKey+AltGraph.
    assert _is_altgr(altgraph=True, is_mac=False) is True


def test_isaltgr_false_for_genuine_ctrl_alt():
    # A real left Ctrl+Alt press leaves AltGraph unset.
    assert _is_altgr(altgraph=False, is_mac=False) is False


def test_isaltgr_false_when_altgraph_set_but_not_ctrl_alt():
    # The collision we defend against is specifically "AltGr reported AS
    # Ctrl+Alt". An event that asserts AltGraph WITHOUT presenting as Ctrl+Alt
    # (e.g. a Linux ISO_Level3_Shift layout, or a stray modifier state) must NOT
    # be swallowed — only a genuine Ctrl+Alt-presenting AltGr keystroke is.
    assert _is_altgr(altgraph=True, ctrl=False, alt=False) is False
    assert _is_altgr(altgraph=True, ctrl=True, alt=False) is False
    assert _is_altgr(altgraph=True, ctrl=False, alt=True) is False


def test_isaltgr_false_on_mac_even_with_altgraph():
    # macOS reports AltGraph=true for the Option key, but Ctrl+Option / Cmd+Option
    # are legitimate Mac shortcuts, so the predicate must never swallow them.
    assert _is_altgr(altgraph=True, is_mac=True) is False


def test_isaltgr_false_when_getmodifierstate_missing():
    # Defensive: an event without getModifierState must not throw or report AltGr.
    assert _is_altgr(altgraph=False, is_mac=False, has_modifier_state=False) is False


# --- The navigator-derived IS_MAC default (dead in node without a stub) -------

def test_is_mac_from_navigator_platform():
    # navigator.platform reports "MacIntel" on EVERY Mac — Apple Silicon
    # (M1/M2/M3...) included; the string was frozen for compatibility, so there
    # is no "MacARM". The regex matches the "Mac" substring, not "Intel".
    assert _is_mac_default(platform="MacIntel") is True


def test_is_mac_from_user_agent_when_platform_blank():
    # iPadOS / some browsers report a Mac userAgent with an unhelpful platform.
    assert _is_mac_default(platform="", user_agent="Mozilla/5.0 (Macintosh; ...)") is True


def test_is_not_mac_on_windows():
    assert _is_mac_default(platform="Win32", user_agent="Mozilla/5.0 (Windows NT 10.0)") is False


# --- _matchesCombo integration (the matcher predicate, end to end) -----------

def test_altgr_keystroke_does_not_trigger_ctrl_alt_shortcut():
    # AZERTY/QWERTZ user holds AltGr over a key that yields 'n'. This must NOT
    # fire the destructive new_session combo.
    ev = {"ctrlKey": True, "altKey": True, "shiftKey": False, "key": "n"}
    assert _matches(ev, "ctrl+alt+n", altgraph=True, is_mac=False) is False


def test_genuine_ctrl_alt_still_matches():
    # A real left Ctrl+Alt press (AltGraph not set) must still work.
    ev = {"ctrlKey": True, "altKey": True, "shiftKey": False, "key": "n"}
    assert _matches(ev, "ctrl+alt+n", altgraph=False, is_mac=False) is True


def test_mac_option_combo_still_matches():
    # macOS reports AltGraph=true for the Option key, but Ctrl+Option / Cmd+Option
    # are legitimate Mac shortcuts. On macOS the guard must NOT swallow them.
    ev = {"ctrlKey": True, "altKey": True, "shiftKey": False, "key": "n"}
    assert _matches(ev, "ctrl+alt+n", altgraph=True, is_mac=True) is True


def test_plain_ctrl_shortcut_unaffected():
    # Non-alt combos were never AltGr-ambiguous and must keep matching.
    ev = {"ctrlKey": True, "altKey": False, "shiftKey": False, "key": "k"}
    assert _matches(ev, "ctrl+k", altgraph=False, is_mac=False) is True
