"""Pin the pure reply-all recipient helpers in emailLibrary/replyRecipients.js.

Regression for issue #360: reply-all dropped every Cc recipient when the user's
own address was unknown, because the old filter used `includes("")` (always
true) instead of an exact-email comparison.
"""
import json

from tests.helpers.node import ROOT, run_node_module

_HELPER = ROOT / "static" / "js" / "emailLibrary" / "replyRecipients.js"


def test_reply_all_keeps_cc_when_self_unknown():
    data = {"to": "Alice <alice@x.com>, bob@x.com", "cc": "Carol <carol@x.com>"}
    js = f"""
    import {{ buildReplyAllCc }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(buildReplyAllCc({json.dumps(data)}, '')));
    """
    cc = run_node_module(js)
    # Empty self address must NOT wipe everyone (the #360 bug).
    assert cc == "Alice <alice@x.com>, bob@x.com, Carol <carol@x.com>"


def test_reply_all_excludes_only_self_exactly():
    data = {"to": "Me <me@x.com>, Alice <alice@x.com>", "cc": "bob@x.com"}
    js = f"""
    import {{ buildReplyAllCc }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(buildReplyAllCc({json.dumps(data)}, 'me@x.com')));
    """
    cc = run_node_module(js)
    # Our own address is dropped; a substring-similar address is kept.
    assert cc == "Alice <alice@x.com>, bob@x.com"


def test_reply_all_excludes_all_of_my_addresses():
    # Multi-account user: every one of their own addresses must be excluded,
    # not just the active one.
    data = {"to": "Alice <alice@x.com>, me@work.com", "cc": "me@personal.com, bob@x.com"}
    js = f"""
    import {{ buildReplyAllCc }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(buildReplyAllCc({json.dumps(data)}, ["me@work.com", "me@personal.com"])));
    """
    cc = run_node_module(js)
    assert cc == "Alice <alice@x.com>, bob@x.com"
