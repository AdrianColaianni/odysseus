"""The `/setup` device-auth flow prints a provider-supplied URL into HTML."""

from pathlib import Path


_SLASH = (Path(__file__).resolve().parent.parent / "static" / "js" / "slashCommands.js").read_text(encoding="utf-8")


def test_setup_device_flow_escapes_the_auth_url():
    start = _SLASH.index("async function _setupProviderDeviceFlow")
    flow_block = _SLASH[start:_SLASH.index("async function _cmdSetup", start)]

    assert 'href="\' + uiModule.esc(authUrl || \'\') + \'"' in flow_block
