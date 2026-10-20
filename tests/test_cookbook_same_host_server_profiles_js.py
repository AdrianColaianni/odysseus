"""Regression guards for same-host Cookbook SSH server profiles (#3337)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HWFIT = (ROOT / "static/js/cookbook-hwfit.js").read_text(encoding="utf-8")
DOWNLOAD = (ROOT / "static/js/cookbookDownload.js").read_text(encoding="utf-8")
SERVE = (ROOT / "static/js/cookbookServe.js").read_text(encoding="utf-8")


def test_no_same_host_selector_paths_resolve_by_first_matching_host():
    forbidden = [
        "servers.find(s => s.host === select.value)",
        "servers.find(s => s.host === _ssEl.value)",
        "servers.find(x => x.host === val)",
        "servers.find(s => s.host === _ssv)",
    ]
    combined = "\n".join([DOWNLOAD, HWFIT, SERVE])
    for needle in forbidden:
        assert needle not in combined
