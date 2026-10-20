"""Issue #3229 and explicit web-toggle regressions.

Bug: allow_bash and allow_web_search were only read from form_data, so JSON
API callers (Content-Type: application/json) always had bash disabled.

Fix: (1) Read from JSON body as fallback.
     (2) Keep bash on the privilege fallback when unset.
     (3) Require an explicit per-turn web setting before exposing web tools.
"""

import ast
import json
from pathlib import Path

import pytest

from src.action_intents import classify_tool_intent
from routes.chat_routes import _is_personal_data_search_without_web_target
from routes.chat_routes import _explicitly_denies_web_lookup
from routes.chat_routes import _contains_explicit_url_target
from routes.chat_routes import _authorizes_exact_url_fetch
from routes.chat_routes import _is_explicit_browser_automation_request
from routes.chat_routes import _is_external_discovery_request
from routes.chat_routes import _prefers_structured_document_tools
from routes.chat_routes import (
    _has_recent_private_browser_success,
    _is_contextual_browser_followup,
)
from routes.chat_routes import _most_recent_successful_web_tool
from routes.chat_routes import _is_contextual_web_followup
from src.tool_policy import (
    is_web_search_explicitly_denied,
    web_intent_may_enable_for_turn,
    web_search_enabled_for_turn,
)
from tests.test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

_CHAT_ROUTES = Path(__file__).resolve().parent.parent / "routes" / "chat_routes.py"


def test_personal_data_search_is_not_mistaken_for_web_search():
    assert _is_personal_data_search_without_web_target(
        "Search saved memory for the Harbor Guji delay."
    )
    assert _is_personal_data_search_without_web_target(
        "Find the prior chat where we fixed the parser."
    )
    assert _is_personal_data_search_without_web_target(
        "Search my previous chats for the Odysseus TUI parser fix."
    )
    assert _is_personal_data_search_without_web_target(
        "Do I have any events today?"
    )
    assert not _is_personal_data_search_without_web_target(
        "Search saved memory, then check the latest news online."
    )


def test_workspace_artifact_paths_are_not_mistaken_for_public_urls():
    assert not _contains_explicit_url_target("Save /workspace/output.md")
    assert not _contains_explicit_url_target("Inspect /workspace/fixtures/video.mp4")
    assert _contains_explicit_url_target("Open https://example.com/report")
    assert _contains_explicit_url_target("Open example.com/report")


def test_plain_pdf_url_is_retrieval_not_browser_automation():
    prompt = "Download and read https://arxiv.org/pdf/2311.08526"

    assert _contains_explicit_url_target(prompt)
    assert not _is_explicit_browser_automation_request(prompt)
    assert _is_explicit_browser_automation_request(
        "Open the page https://example.com/report and click the details link"
    )
    assert _is_explicit_browser_automation_request(
        "Open https://example.com with the private browesr"
    )


def test_authoritative_source_discovery_is_web_intent():
    assert _is_external_discovery_request(
        "Find the official announcement and tell me the date."
    )
    assert _is_external_discovery_request("Locate the press release")
    assert not _is_external_discovery_request("Find my announcement note")


def test_exact_public_url_authorizes_fetch_without_broad_search():
    assert _authorizes_exact_url_fetch(
        "Summarize https://example.com/reports/quarterly"
    )
    assert not _authorizes_exact_url_fetch(
        "Open https://example.com and click the details link"
    )
    assert not _authorizes_exact_url_fetch(
        "Summarize https://youtu.be/example"
    )
    assert not _authorizes_exact_url_fetch(
        "Do not search or fetch https://example.com/private"
    )


def test_external_paper_tables_prefer_structured_tools_over_shell():
    assert _prefers_structured_document_tools(
        'From the paper "Example Suite", merge Table 2 and Table 4.'
    )
    assert _prefers_structured_document_tools(
        "Download and read https://arxiv.org/pdf/2311.08526"
    )
    assert not _prefers_structured_document_tools(
        "Extract Table 2 from /workspace/fixtures/paper.pdf"
    )


def test_chat_stream_reads_tool_toggles_from_json_body():
    """#3229: JSON callers set these toggles in the body, not the form.

    Source-level because the turn contract masks the toggles in the route's
    observable tool set.
    """
    source = _CHAT_ROUTES.read_text(encoding="utf-8")
    chat_stream = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "chat_stream"
    )
    for name in ("allow_bash", "allow_web_search"):
        assignments = [
            ast.get_source_segment(source, node) for node in ast.walk(chat_stream)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        ]
        assert any("body" in segment for segment in assignments), name
    assert "allow_bash is not None" in source


def test_clean_private_browser_warmth_requires_typed_success():
    successful = type("Session", (), {"history": [{
        "role": "assistant",
        "metadata": {"tool_events": [{
            "tool": "private_browser", "exit_code": 0, "error": False,
        }]},
    }]})()
    failed = type("Session", (), {"history": [{
        "role": "assistant",
        "metadata": {"tool_events": [{
            "tool": "private_browser", "exit_code": 1, "error": True,
        }]},
    }]})()
    prose_only = type("Session", (), {"history": [{
        "role": "assistant", "content": "I used private_browser",
    }]})()

    assert _has_recent_private_browser_success(successful)
    assert not _has_recent_private_browser_success(failed)
    assert not _has_recent_private_browser_success(prose_only)


def test_retry_on_that_page_is_a_contextual_browser_followup():
    session = type("Session", (), {"history": [
        {"role": "user", "content": "Go to example.com in the browser."},
        {"role": "assistant", "content": "Opened the page."},
    ]})()

    assert _is_contextual_browser_followup(
        "Try again on that page and compare the prices.", session,
    )


def test_contextual_browser_followup_recognizes_current_page_inspection():
    session = type("Session", (), {"history": [{
        "role": "user",
        "content": "Browse https://example.com and take a snapshot.",
    }]})()

    assert _is_contextual_browser_followup(
        "What heading is visible on that page? Check the current page before answering.",
        session,
    )
    assert not _is_contextual_browser_followup("Show my notes.", session)


async def _clean_route_contract(monkeypatch, message, *, history=(), native=False):
    from routes import chat_routes
    from src import tool_security

    with monkeypatch.context() as route_patch:
        endpoint = _chat_stream_endpoint(
            route_patch, "agent", {},
            session_model="odysseus-qwen3.5-tools-pre-heretic",
            session_history=history,
        )
        route_patch.setattr(
            chat_routes, "coerce_message_and_session",
            lambda *args, **kwargs: (message, "session-1"),
        )
        route_patch.setattr(
            tool_security, "owner_is_admin_or_single_user", lambda owner: True,
        )
        observed = []

        async def capture_agent(*args, **kwargs):
            observed.append(kwargs["turn_contract"])
            yield 'data: {"delta":"Contract constructed."}\n\n'
            yield "data: [DONE]\n\n"

        route_patch.setattr(chat_routes, "stream_agent_loop", capture_agent)
        request = _RouteRequest("agent")
        request._form.update({"message": message, "compare_mode": "false"})
        if native:
            request._form.update({
                "cwd": "/tmp/native-workspace",
                "workspace": "/tmp/native-workspace",
                "client_runtime_context": json.dumps({
                    "surface": "odysseus-native", "terminal_agent": True,
                    "unattended_mode": True,
                    "input_files": ["/workspace/paper.pdf"],
                }),
            })
        response = await endpoint(request)
        async for _ in response.body_iterator:
            pass
        assert len(observed) == 1
        return observed[0]


@pytest.mark.asyncio
async def test_clean_browser_filter_preserves_native_pdf_extraction_contract(monkeypatch):
    contract = await _clean_route_contract(
        monkeypatch,
        "Extract Table 2 from /workspace/paper.pdf using pdf_extract.",
        native=True,
    )
    assert contract.capabilities == {"shell_files"}
    assert contract.permits("pdf_extract")
    assert "private_browser" not in contract.offered
    assert not {"manage_tasks", "search_emails", "send_email"} & contract.offered


@pytest.mark.asyncio
async def test_clean_preview_only_offers_browser_for_explicit_or_typed_warm_turns(monkeypatch):
    message = "Summarize the status."
    no_history = await _clean_route_contract(monkeypatch, message)
    failed_history = [{"role": "assistant", "metadata": {"tool_events": [{
        "tool": "private_browser", "exit_code": 1, "error": True,
    }]}}]
    failed = await _clean_route_contract(monkeypatch, message, history=failed_history)
    successful_history = [{"role": "assistant", "metadata": {"tool_events": [{
        "tool": "private_browser", "exit_code": 0, "error": False,
    }]}}]
    warm = await _clean_route_contract(monkeypatch, message, history=successful_history)
    explicit = await _clean_route_contract(
        monkeypatch, "Open https://example.com with the private browser",
    )
    assert "private_browser" not in no_history.offered
    assert "private_browser" not in failed.offered
    assert warm.permits("private_browser")
    assert explicit.permits("private_browser")


@pytest.mark.asyncio
async def test_explicit_web_fetch_is_not_erased_by_generic_browser_intent(monkeypatch):
    contract = await _clean_route_contract(
        monkeypatch,
        "Use web_fetch to read https://example.com/report in the private browser.",
    )
    assert contract.capabilities == {"search_browser"}
    assert contract.required == {"web_fetch"}
    assert contract.permits("web_fetch")
    assert not {"manage_tasks", "search_emails", "send_email"} & contract.offered


def test_web_followup_grammar_covers_article_detail_questions():
    from routes.chat_routes import _WEB_FOLLOWUP_RE

    assert _WEB_FOLLOWUP_RE.fullmatch("What else did it say about Miro?")
    assert _WEB_FOLLOWUP_RE.fullmatch("What did it say about pricing?")
    assert _WEB_FOLLOWUP_RE.fullmatch("grab the top story and read it")
    assert _WEB_FOLLOWUP_RE.fullmatch(
        "now pull the page title and last-updated date off that link"
    )


def test_contextual_web_followup_recognizes_referential_result_open():
    session = type("Session", (), {"history": [{
        "role": "user",
        "content": "look up what's happening in germany rn",
    }]})()

    assert _is_contextual_web_followup("grab the top story and read it", session)


def test_web_followup_retains_only_latest_successful_public_web_tool():
    session = type("Session", (), {"history": [
        {"role": "assistant", "metadata": {"tool_events": [
            {"tool": "web_search", "exit_code": 0},
            {"tool": "web_fetch", "exit_code": 0},
        ]}},
    ]})()
    assert _most_recent_successful_web_tool(session) == "web_fetch"


def test_failed_web_tool_is_not_retained_for_followup():
    session = type("Session", (), {"history": [
        {"role": "assistant", "metadata": {"tool_events": [
            {"tool": "web_fetch", "exit_code": 1, "error": True},
        ]}},
    ]})()
    assert _most_recent_successful_web_tool(session) is None


def test_native_declared_input_files_establish_workspace_intent():
    from routes.chat_routes import _native_context_has_workspace_inputs

    assert _native_context_has_workspace_inputs({
        "surface": "odysseus-native",
        "terminal_agent": True,
        "input_files": ["/workspace/fixtures/video.mp4"],
    })
    assert not _native_context_has_workspace_inputs({
        "surface": "odysseus-native",
        "terminal_agent": False,
        "input_files": ["/workspace/fixtures/video.mp4"],
    })


def test_chat_tool_privileges_use_effective_bearer_owner():
    """Bearer TUI/WebUI turns must not be denied as the synthetic ``api`` user."""
    source = _CHAT_ROUTES.read_text(encoding="utf-8")
    privilege_gate = source[source.index("# Enforce per-user privileges"):]
    assert "_user = effective_user(request)" in privilege_gate
    assert "_user = ctx.user" not in privilege_gate


def test_web_tools_need_an_explicit_turn_setting_and_denial_wins():
    assert web_search_enabled_for_turn("true")
    assert web_search_enabled_for_turn(None, use_web="true")
    assert not web_search_enabled_for_turn(None)
    assert not web_search_enabled_for_turn("false", use_web="true")
    for denial in (False, "false", "0", "off"):
        assert is_web_search_explicitly_denied(denial), denial
        assert web_intent_may_enable_for_turn(denial) is False, denial


def test_prompt_web_wording_is_classified_as_web_intent():
    for message in ("search the web for current CVEs", "look this up and answer with sources"):
        intent = classify_tool_intent(message)
        assert intent is not None and intent.category == "web", message


def test_missing_web_toggle_can_be_inferred_from_prompt_intent():
    assert web_intent_may_enable_for_turn(None) is True
    assert web_intent_may_enable_for_turn(
        None,
        message_denies_lookup=True,
    ) is False


def test_explicit_no_search_phrase_blocks_web_auto_enable():
    assert _explicitly_denies_web_lookup("answer from memory only, do not search")


_CHAT_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "chat.js"


def test_frontend_always_sends_explicit_allow_bash():
    """chat.js must always send allow_bash (both true and false), not only on toggle ON."""
    source = _CHAT_JS.read_text(encoding="utf-8")
    # Must not only append 'true' — must also handle the false case
    assert "allow_bash', el('bash-toggle').checked ? 'true' : 'false'" in source or \
           "allow_bash', 'false'" in source, (
        "Frontend must send explicit allow_bash=false when toggle is off"
    )


def test_frontend_generic_web_prose_does_not_grant_shell_authority():
    source = _CHAT_JS.read_text(encoding="utf-8")
    workspace_line = next(
        line for line in source.splitlines()
        if "const workspaceAgentIntent" in line
    )
    for generic in ("source", "system", "app", "change", "review", "server", "api"):
        assert generic not in workspace_line, generic
    assert "_explicitWorkspaceTarget" in workspace_line
