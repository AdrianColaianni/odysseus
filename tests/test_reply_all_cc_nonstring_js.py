"""Pin buildReplyAllCc (static/js/emailLibrary/replyRecipients.js) against a
non-string To/Cc.
"""
import json

from tests.helpers.node import ROOT, run_node_module

_HELPER = ROOT / "static" / "js" / "emailLibrary" / "replyRecipients.js"


def _cc(data, mine):
    return run_node_module(f"""
    import {{ buildReplyAllCc }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(buildReplyAllCc({json.dumps(data)}, {json.dumps(mine)})));
    """)


def test_build_reply_all_cc_tolerates_non_string_fields():
    # data.to / data.cc come from a JSON message blob and are not always
    # strings; the old (s || "").split crashed on a non-string To.
    out = _cc({"to": 123, "cc": "a@x.com, b@x.com"}, "me@x.com")
    assert out == "a@x.com, b@x.com"


def test_build_reply_all_cc_still_excludes_self():
    out = _cc({"to": "me@x.com, a@x.com", "cc": ""}, "me@x.com")
    assert out == "a@x.com"
