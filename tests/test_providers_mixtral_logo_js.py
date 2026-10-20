"""Pin the Mistral provider-logo pattern to cover Mixtral and Ministral.

The pattern was /mistral/i, which does not match "mixtral" (note the x) or
"ministral" -- Mistral AI's flagship MoE and edge families -- so those models
rendered with no provider logo unless they carried a "mistralai/" prefix.
"""
import json

from tests.helpers.node import ROOT, run_node_module

_HELPER = ROOT / "static" / "js" / "providers.js"


def _has_logo(model):
    return run_node_module(
        f"import {{ providerLogo }} from '{_HELPER.as_posix()}';"
        f"console.log(JSON.stringify(providerLogo({json.dumps(model)}) !== null));"
    )


def test_mixtral_ministral_get_a_logo():
    assert _has_logo("mixtral-8x7b") is True
    assert _has_logo("ministral-8b") is True
    assert _has_logo("mistral-large-latest") is True


def test_unknown_vendor_has_no_logo():
    assert _has_logo("totally-unknown-model-xyz") is False
