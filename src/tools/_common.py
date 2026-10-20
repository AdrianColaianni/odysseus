"""Shared helpers used across tool implementation domains."""
import functools
from typing import Dict, Optional

from core.constants import internal_api_base
from src.tool_utils import _parse_tool_args


# In-process loopback base for agent tools that call Odysseus's own API
# (cookbook state, model serve, gallery, email, calendar). We ride the
# per-process internal token so require_admin lets us through. See
# core/middleware.py.
_INTERNAL_BASE = internal_api_base()


def _internal_headers(owner: Optional[str] = None) -> Dict[str, str]:
    from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
    headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
    if owner:
        headers["X-Odysseus-Owner"] = owner
    return headers


def parsed_tool_args(fn):
    """Call a `do_*(args, ...)` tool with the parsed argument dict instead of the raw blob."""
    @functools.wraps(fn)
    async def wrapper(content, *rest, **kwargs):
        try:
            args = _parse_tool_args(content)
        except ValueError:
            return {"error": "Invalid JSON arguments", "exit_code": 1}
        return await fn(args, *rest, **kwargs)
    return wrapper
