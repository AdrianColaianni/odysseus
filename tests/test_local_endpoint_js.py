"""Pin the billing/display classifier `isLocalEndpoint` in chatRenderer.js.

Self-hosted endpoints reached by a bare Docker/Compose service name (e.g.
`http://llamaswap:8000`) must classify as LOCAL so they aren't priced at cloud
rates against the substring-matched MODEL_PRICING table. Cloud FQDNs must stay
billable.

The function is extracted from source because chatRenderer.js pulls in
browser-only modules and cannot be imported under Node.
"""
import json
import re
from pathlib import Path

from tests.helpers.node import run_node_module

_SRC = Path(__file__).resolve().parent.parent / "static" / "js" / "chatRenderer.js"


def _classify(urls):
    m = re.search(r"export function isLocalEndpoint\(.*?\n\}", _SRC.read_text(encoding="utf-8"), re.DOTALL)
    assert m, "isLocalEndpoint not found in chatRenderer.js"
    fn = m.group(0).replace("export function", "function", 1)
    return run_node_module(fn + f"\nconsole.log(JSON.stringify({json.dumps(urls)}.map(isLocalEndpoint)));")


def test_self_hosted_endpoints_classify_local():
    urls = [
        "http://llamaswap:8000",  # bare Docker/Compose service name
        "http://127.0.0.1:11434",
        "http://192.168.50.244",  # private ranges
        "http://172.16.0.9",
        "http://server.local",  # mDNS
    ]
    assert dict(zip(urls, _classify(urls))) == {url: True for url in urls}


def test_cloud_endpoints_classify_billable():
    urls = ["https://api.openai.com/v1", "https://openrouter.ai/api/v1"]
    assert dict(zip(urls, _classify(urls))) == {url: False for url in urls}
