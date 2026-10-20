"""Regression: agent_max_tool_calls must not crash chat_stream when settings.json
holds a non-numeric string (e.g. {"agent_max_tool_calls": "unlimited"}).

The HTTP admin endpoint validates/clamps this value, but a hand-edited or
agent-written data/settings.json bypasses that. The read sits inside the agent
streaming try-block whose only handler catches (CancelledError, GeneratorExit) —
NOT ValueError — so an unguarded int() would propagate and break the SSE stream.
It must be guarded like the agent_max_rounds read four lines below.
"""
import ast
from pathlib import Path


_CHAT_ROUTES = Path(__file__).resolve().parent.parent / "routes" / "chat_routes.py"


def _tool_budget_read_is_guarded(source: str) -> bool:
    """True if a `try` that assigns `_tool_budget` also catches ValueError."""
    tree = ast.parse(source)
    chat_stream = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "chat_stream"),
        None,
    )
    assert chat_stream is not None, "chat_stream function not found"
    for try_node in ast.walk(chat_stream):
        if not isinstance(try_node, ast.Try):
            continue
        # Only the immediate try body — not nested trys — should own the assignment.
        assigns_budget = any(
            isinstance(t, ast.Name) and t.id == "_tool_budget"
            for stmt in try_node.body if isinstance(stmt, ast.Assign)
            for t in stmt.targets
        )
        if not assigns_budget:
            continue
        catches_value_error = any(
            (isinstance(h.type, ast.Name) and h.type.id == "ValueError")
            or (isinstance(h.type, ast.Tuple)
                and any(isinstance(e, ast.Name) and e.id == "ValueError" for e in h.type.elts))
            for h in try_node.handlers
        )
        if catches_value_error:
            return True
    return False


def test_tool_budget_read_is_wrapped_in_try_except():
    source = _CHAT_ROUTES.read_text(encoding="utf-8")
    assert _tool_budget_read_is_guarded(source), (
        "_tool_budget = int(get_setting('agent_max_tool_calls', 0)) must be wrapped in "
        "try/except (ValueError) like the agent_max_rounds read, so a non-numeric "
        "settings.json value cannot crash chat_stream during agent init"
    )

