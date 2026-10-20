"""providerLabel() in providers.js must NOT name the serving tool from the port,
mirroring the Python _provider_label() in src/llm_core.py.

A port is not authoritative: vLLM, SGLang, llama.cpp and plain OpenAI-compatible
servers all routinely share 8000/8080, so a port-only label would mislabel real
setups (e.g. a vLLM box on :8080 shown as "llama.cpp"). The actual tool is
identified by probing /props during discovery and stored as the endpoint's name.
The rule here: loopback → "Local"; private-LAN IPs → "Local"; known remote
provider hosts → their provider name.
"""
import json

from tests.helpers.node import ROOT, run_node_module

_SRC = ROOT / "static" / "js" / "providers.js"


def _provider_label(url: str) -> str | None:
    src = _SRC.read_text(encoding="utf-8")
    # Strip the `export` keyword so the module runs standalone.
    src_runnable = src.replace("export function providerLabel", "function providerLabel")
    src_runnable = src_runnable.replace("export default {", "const _default = {")
    return run_node_module(src_runnable + f"\nconsole.log(JSON.stringify(providerLabel({json.dumps(url)})));")


def test_provider_label_neutral_for_loopback():
    for url, expected in [
        ("http://localhost:8080/v1", "Local"),
        ("http://192.168.1.50:8080", "Local"),
        ("https://api.openai.com/v1", "OpenAI"),
        ("https://api.groq.com/openai/v1", "Groq"),
    ]:
        assert _provider_label(url) == expected, url
