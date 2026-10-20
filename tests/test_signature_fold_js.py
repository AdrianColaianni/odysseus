from tests.helpers.node import run_node_module


def test_extract_quote_meta_ignores_non_string_inputs():
    values = run_node_module(
        """
        globalThis.document = {
          createElement() {
            return {
              set textContent(value) { this._text = value; },
              get innerHTML() { return this._text || ''; }
            };
          }
        };
        const { _extractQuoteMeta } = await import('./static/js/emailLibrary/signatureFold.js');
        console.log(JSON.stringify({
          nullValue: _extractQuoteMeta(null),
          objectValue: _extractQuoteMeta({bad: true})
        }));
        """
    )

    assert values == {"nullValue": "", "objectValue": ""}


def test_extract_quote_meta_keeps_outlook_headers():
    values = run_node_module(
        """
        globalThis.document = {
          createElement() {
            return {
              set textContent(value) { this._text = value; },
              get innerHTML() { return this._text || ''; }
            };
          }
        };
        const { _extractQuoteMeta } = await import('./static/js/emailLibrary/signatureFold.js');
        const html = 'From: Alice <alice@example.com> Sent: Monday, May 4, 2026 To: Bob Subject: hi';
        console.log(JSON.stringify({ meta: _extractQuoteMeta(html) }));
        """
    )

    assert values["meta"] == "Alice · Monday, May 4, 2026"
