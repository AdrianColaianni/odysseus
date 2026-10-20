"""Pin ArrowUp recall on the chat composer (static/js/composerArrowUpRecall.js).

Driven through `node --input-type=module` so we exercise the real JS without a
full Vitest/Jest setup (same approach as test_reply_recipients_js.py). Skips
when `node` is not installed rather than failing.

Locks in: empty composer recalls user messages from the active conversation,
repeated ArrowUp walks older prompts in that same chat; non-empty composer is
untouched unless it contains the recalled prompt; multiline caret navigation is
not hijacked; Shift/Alt/Ctrl/Meta+ArrowUp are ignored; IME composition does not
trigger recall; messages are read from #chat-history (dataset.raw), not session
sidebar metadata.
"""
import json
from pathlib import Path

from tests.helpers.node import run_node_module

_REPO = Path(__file__).resolve().parent.parent
_HELPER = _REPO / "static" / "js" / "composerArrowUpRecall.js"
_HELPER_URL = _HELPER.as_uri()

_HARNESS = r"""
import { wireArrowUpRecall } from 'HELPER_PATH';

function makeComposer(initial = '') {
  const listeners = [];
  const composer = {
    value: initial,
    selectionStart: initial.length,
    selectionEnd: initial.length,
    dataset: {},
    _arrowUpRecallWired: false,
    addEventListener(type, fn) {
      if (type === 'keydown') listeners.push(fn);
    },
    dispatchKey(opts = {}) {
      let prevented = false;
      let stopped = false;
      let immediateStopped = false;
      const e = {
        key: opts.key ?? 'ArrowUp',
        shiftKey: !!opts.shiftKey,
        altKey: !!opts.altKey,
        ctrlKey: !!opts.ctrlKey,
        metaKey: !!opts.metaKey,
        isComposing: !!opts.isComposing,
        preventDefault() { prevented = true; },
        stopPropagation() { stopped = true; },
        stopImmediatePropagation() { immediateStopped = true; },
      };
      for (const fn of listeners) fn(e);
      return { prevented, stopped, immediateStopped };
    },
  };
  return composer;
}

function runCase(body) {
  const composer = makeComposer(body.initial ?? '');
  if (body.caret != null) {
    composer.selectionStart = body.caret;
    composer.selectionEnd = body.caretEnd ?? body.caret;
  }
  const last = body.history ?? body.last ?? 'previous message';
  let resized = false;
  wireArrowUpRecall(composer, () => last, {
    autoResize: () => { resized = true; },
  });
  const events = body.events ?? [body.event ?? {}];
  const handled = events.map(ev => composer.dispatchKey(ev));
  return {
    value: composer.value,
    selectionStart: composer.selectionStart,
    selectionEnd: composer.selectionEnd,
    prevented: handled.map(v => v.prevented),
    stopped: handled.map(v => v.stopped),
    immediateStopped: handled.map(v => v.immediateStopped),
    resized,
  };
}

const cases = CASES_JSON;
const results = cases.map(runCase);
console.log(JSON.stringify(results));
""".replace("HELPER_PATH", _HELPER_URL)


def _run(cases: list) -> list:
    js = _HARNESS.replace("CASES_JSON", json.dumps(cases))
    return run_node_module(js)


def test_empty_composer_recalls_last_user_message():
    out = _run([{"initial": "", "last": "hello again"}])[0]
    assert out["value"] == "hello again"
    assert out["selectionStart"] == len("hello again")
    assert out["selectionEnd"] == len("hello again")
    assert out["prevented"] == [True]
    assert out["stopped"] == [True]
    assert out["immediateStopped"] == [True]
    assert out["resized"] is True


def test_repeated_arrow_up_cycles_current_chat_prompts_newest_first():
    out = _run([{
        "initial": "",
        "history": ["third prompt", "second prompt", "first prompt"],
        "events": [{}, {}, {}, {}],
    }])[0]
    assert out["value"] == "first prompt"
    assert out["selectionStart"] == len("first prompt")
    assert out["prevented"] == [True, True, True, True]
    assert out["stopped"] == [True, True, True, True]
    assert out["immediateStopped"] == [True, True, True, True]
    assert out["resized"] is True


def test_non_empty_composer_does_not_recall():
    out = _run([{"initial": "draft in progress", "last": "ignored"}])[0]
    assert out["value"] == "draft in progress"
    assert out["prevented"] == [False]
    assert out["resized"] is False


def test_whitespace_only_composer_is_not_empty():
    out = _run([{"initial": "   ", "last": "ignored"}])[0]
    assert out["value"] == "   "
    assert out["prevented"] == [False]


def test_multiline_caret_navigation_preserved():
    # Caret on line 2 — ArrowUp must not recall or preventDefault.
    text = "line one\nline two"
    out = _run([{"initial": text, "caret": len(text), "last": "ignored"}])[0]
    assert out["value"] == text
    assert out["selectionStart"] == len(text)
    assert out["prevented"] == [False]


def test_modified_arrow_up_ignored():
    cases = [
        {"initial": "", "event": {"shiftKey": True}},
        {"initial": "", "event": {"altKey": True}},
        {"initial": "", "event": {"ctrlKey": True}},
        {"initial": "", "event": {"metaKey": True}},
    ]
    for out in _run(cases):
        assert out["value"] == ""
        assert out["prevented"] == [False]


def test_ime_composition_does_not_trigger_recall():
    out = _run([{"initial": "", "event": {"isComposing": True}, "last": "ignored"}])[0]
    assert out["value"] == ""
    assert out["prevented"] == [False]


def test_no_recall_when_last_message_missing():
    out = _run([{"initial": "", "last": ""}])[0]
    assert out["value"] == ""
    assert out["prevented"] == [False]
    assert out["resized"] is False


def test_wire_is_idempotent():
    js = f"""
    import {{ wireArrowUpRecall }} from '{_HELPER_URL}';
    const composer = {{ _arrowUpRecallWired: false, addEventListener() {{}} }};
    const ok1 = wireArrowUpRecall(composer, () => 'x');
    const ok2 = wireArrowUpRecall(composer, () => 'y');
    console.log(JSON.stringify({{ ok1, ok2, wired: composer._arrowUpRecallWired }}));
    """
    assert run_node_module(js) == {"ok1": True, "ok2": True, "wired": True}


def test_get_last_user_message_from_chat_history():
    js = f"""
    import {{
      getLastUserMessageFromChatHistory,
      getUserMessagesFromChatHistory,
    }} from '{_HELPER_URL}';

    const chatBox = {{
      id: 'chat-history',
      querySelectorAll(sel) {{
        if (sel !== '.msg-user') return [];
        return [
          {{ dataset: {{ raw: 'first' }}, querySelector: () => null }},
          {{ dataset: {{ raw: 'last raw' }}, querySelector: () => null }},
        ];
      }},
    }};

    const doc = {{
      getElementById(id) {{ return id === 'chat-history' ? chatBox : null; }},
    }};

    console.log(JSON.stringify({{
      fromChat: getLastUserMessageFromChatHistory(doc),
      fromBox: getLastUserMessageFromChatHistory(chatBox),
      allFromChat: getUserMessagesFromChatHistory(doc),
      empty: getLastUserMessageFromChatHistory({{ getElementById: () => null }}),
      noUsers: getLastUserMessageFromChatHistory({{
        getElementById: () => ({{ querySelectorAll: () => [] }}),
      }}),
    }}));
    """
    assert run_node_module(js) == {
        "fromChat": "last raw",
        "fromBox": "last raw",
        "allFromChat": ["last raw", "first"],
        "empty": "",
        "noUsers": "",
    }


def test_integration_recalls_from_chat_history_dom():
    js = f"""
    import {{
      wireArrowUpRecall,
      getUserMessagesFromChatHistory,
    }} from '{_HELPER_URL}';

    const chatBox = {{
      id: 'chat-history',
      querySelectorAll(sel) {{
        if (sel !== '.msg-user') return [];
        return [{{ dataset: {{ raw: 'stored prompt' }}, querySelector: () => null }}];
      }},
    }};
    const doc = {{ getElementById: (id) => (id === 'chat-history' ? chatBox : null) }};

    const listeners = [];
    const composer = {{
      value: '',
      selectionStart: 0,
      selectionEnd: 0,
      dataset: {{}},
      _arrowUpRecallWired: false,
      addEventListener(type, fn) {{ if (type === 'keydown') listeners.push(fn); }},
    }};
    wireArrowUpRecall(composer, () => getUserMessagesFromChatHistory(doc));
    let prevented = false;
    listeners[0]({{
      key: 'ArrowUp',
      shiftKey: false,
      altKey: false,
      ctrlKey: false,
      metaKey: false,
      isComposing: false,
      preventDefault() {{ prevented = true; }},
    }});
    console.log(JSON.stringify({{ value: composer.value, prevented }}));
    """
    assert run_node_module(js) == {"value": "stored prompt", "prevented": True}


def test_prompt_recall_is_not_duplicated_in_app_js():
    """Only composerArrowUpRecall.js may own ArrowUp on #message (issue #5862).

    static/app.js once carried a near-verbatim copy of this recall logic, wired
    as a second capture-phase listener on the same textarea. That copy lacked
    the draft guard here, and because it called stopImmediatePropagation it won
    regardless of registration order — so a typed multi-line prompt was replaced
    by the last sent one instead of the caret moving up a line.
    """
    app_js = (_REPO / "static" / "app.js").read_text(encoding="utf-8")
    for marker in (
        "_odysseusPromptRecallCapture",
        "_readComposerPromptHistory",
        "odysseusRecallIndex",
    ):
        assert marker not in app_js, (
            f"static/app.js reintroduces prompt recall ({marker!r}); "
            "it belongs to static/js/composerArrowUpRecall.js alone"
        )
