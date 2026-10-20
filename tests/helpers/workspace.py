"""Bind the agent's active workspace for the body of a test."""
import os
from contextlib import contextmanager

from src.tool_execution import _active_workspace


@contextmanager
def workspace_at(path):
    """Set `_active_workspace` to `path` and reset it on exit.

    A ContextVar token cannot be reset from fixture teardown, which runs in a
    different context, so this is a context manager rather than a fixture.
    """
    token = _active_workspace.set(os.path.realpath(path))
    try:
        yield
    finally:
        _active_workspace.reset(token)
