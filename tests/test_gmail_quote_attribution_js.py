"""Pin _extractQuoteMeta's Gmail attribution parsing (static/js/emailLibrary/signatureFold.js).

Regression: the Gmail-fallback date pattern allowed only ONE comma before the
4-digit year, but the standard US Gmail attribution
"On Mon, Apr 18, 2026 at 9:31 AM, Jane Doe <jane@example.com> wrote:" carries
TWO (after the weekday and after the day-of-month). The match failed, so the
collapsed "Earlier thread"/"Earlier reply" fold rendered without its
sender/date headline for the most common Gmail reply format.
"""
import json
from pathlib import Path

from tests.helpers.node import run_node_module

_HELPER = Path(__file__).resolve().parent.parent / "static" / "js" / "emailLibrary" / "signatureFold.js"


def _meta(html: str) -> str:
    js = (
        # _esc in the module touches `document` lazily; stub it so the module
        # can be exercised outside a browser.
        "globalThis.document = { createElement() { return {"
        " set textContent(v) { this._t = v; },"
        " get innerHTML() { return this._t || ''; } }; } };"
        f"const {{ _extractQuoteMeta }} = await import('{_HELPER.as_posix()}');"
        f"console.log(JSON.stringify(_extractQuoteMeta({json.dumps(html)})));"
    )
    return run_node_module(js)


def test_us_gmail_attribution_with_weekday_extracts_sender_and_date():
    meta = _meta("On Mon, Apr 18, 2026 at 9:31 AM, Jane Doe &lt;jane@example.com&gt; wrote:")
    # date is clamped to 28 chars by the helper; sender must be present.
    assert meta.startswith("Jane Doe jane@example.com")
    assert "Mon, Apr 18, 2026" in meta


def test_gmail_attribution_without_time_extracts_sender():
    meta = _meta("On Wed, Jan 1, 2025, Jane wrote:")
    assert meta == "Jane · Wed, Jan 1, 2025"


def test_previously_working_formats_still_match():
    # No weekday (single comma before the year).
    meta = _meta("On Apr 18, 2026 at 9:31 AM, Jane Doe wrote:")
    assert meta.startswith("Jane Doe · Apr 18, 2026")
    # UK/intl day-before-month order.
    meta = _meta("On Mon, 18 Apr 2026 at 09:31, Jane Doe &lt;jane@example.com&gt; wrote:")
    assert meta.startswith("Jane Doe jane@example.com")
