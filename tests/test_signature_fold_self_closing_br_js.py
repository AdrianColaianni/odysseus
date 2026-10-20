"""Pin the RFC-3676 "-- " signature delimiter fold for self-closing breaks.

_foldSignature folded the standard "-- " sig delimiter only when the
surrounding line breaks were the literal `<br>`; the regex missed `<br/>`
and `<br />` (what Apple Mail and many clients emit), even though the very
next matcher in the same function already uses `<br\\s*/?>`. So a plain-text
signature delimiter with self-closing breaks was never folded.
"""
import json

from tests.helpers.node import run_node_module


def _folds(html):
    return run_node_module(f"""
    globalThis.document = {{ createElement: () => {{ let t=''; return {{ set textContent(v){{t=String(v);}}, get innerHTML(){{return t;}} }}; }} }};
    const mod = await import('./static/js/emailLibrary/signatureFold.js');
    const html = {json.dumps(html)};
    const out = mod._foldSignature(html, null);
    console.log(JSON.stringify(out.includes('email-sig-fold')));
    """)


_SIG = "X" * 250  # long enough to be a "bloated" foldable signature


def test_self_closing_br_delimiter_folds():
    assert _folds(f"Hello, please review.<br />-- <br />John Smith<br />Acme<br />{_SIG}") is True
    assert _folds(f"Hi.<br/>-- <br/>Jane Doe<br/>{_SIG}") is True


def test_classic_br_delimiter_still_folds():
    assert _folds(f"Hello.<br>-- <br>John Smith<br>{_SIG}") is True


def test_short_signature_is_not_folded():
    # not bloated -> wrap() returns the html unchanged (no fold)
    assert _folds("Hello.<br />-- <br />JS") is False
