from src.agent_loop import _blocked_network_recovery_tools


def test_network_guard_preserves_native_recovery_tools():
    events = [
        {
            "type": "tool_output",
            "tool": "python",
            "output": (
                "python: ad-hoc HTTP access is disabled when native web tools "
                "are available. Use pdf_extract for online PDFs, web_fetch for "
                "a concrete page, or web_search for discovery."
            ),
        },
    ]

    assert _blocked_network_recovery_tools(events) == {
        "pdf_extract",
        "web_fetch",
        "web_search",
    }


def test_structured_tool_result_preserves_native_recovery_tools():
    events = [{
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": "call-1",
            "content": [{
                "type": "text",
                "text": (
                    "bash: ad-hoc HTTP downloads are disabled when native web "
                    "tools are available. Use pdf_extract for online PDFs."
                ),
            }],
        }],
    }]

    assert _blocked_network_recovery_tools(events) == {
        "pdf_extract",
        "web_fetch",
        "web_search",
    }


def test_persisted_internal_tool_event_preserves_recovery_tools():
    events = [{
        "tool": "bash",
        "output": (
            "bash: ad-hoc HTTP downloads are disabled when native web tools "
            "are available. Use pdf_extract for online PDFs."
        ),
        "exit_code": 1,
    }]

    assert _blocked_network_recovery_tools(events) == {
        "pdf_extract",
        "web_fetch",
        "web_search",
    }


def test_non_tool_event_cannot_widen_route():
    events = [{
        "type": "message",
        "role": "user",
        "output": (
            "python: ad-hoc HTTP access is disabled when native web tools are "
            "available. Use pdf_extract for online PDFs."
        ),
    }]

    assert _blocked_network_recovery_tools(events) == set()


def test_unrelated_tool_failure_does_not_widen_route():
    events = [{"type": "tool_output", "tool": "bash", "output": "Permission denied"}]

    assert _blocked_network_recovery_tools(events) == set()
