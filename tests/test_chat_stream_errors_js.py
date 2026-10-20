"""Execute terminal stream-error classification under Node."""

import json
from pathlib import Path

from tests.helpers.node import run_node_module


_REPO = Path(__file__).resolve().parents[1]
_MODULE = (_REPO / "static" / "js" / "chatStreamErrors.js").as_uri()


def test_terminal_provider_errors_preserve_text_and_never_auto_retry():
    script = f"""
      import {{ createTerminalStreamError, isRecoverableStreamError }} from {json.dumps(_MODULE)};
      const stringError = createTerminalStreamError({{ status: 401, error: 'invalid key' }});
      const objectError = createTerminalStreamError({{ status: 404, error: {{ message: 'model missing' }} }});
      console.log(JSON.stringify({{
        stringMessage: stringError.message,
        objectMessage: objectError.message,
        terminalRecoverable: isRecoverableStreamError(stringError),
        eofRecoverable: isRecoverableStreamError(new Error('Stream closed before completion')),
        networkRecoverable: isRecoverableStreamError(new TypeError('fetch failed')),
      }}));
    """
    assert run_node_module(script) == {
        "stringMessage": "invalid key",
        "objectMessage": "model missing",
        "terminalRecoverable": False,
        "eofRecoverable": True,
        "networkRecoverable": True,
    }
