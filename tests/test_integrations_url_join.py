"""Tests for integration URL construction in execute_api_call.

Covers the trailing-slash regression from #5138: a bare "/" path must
resolve to the base URL itself, not base + "/". Discord webhook URLs
404 on the trailing-slash variant, so api_call against a
POST-to-base integration silently failed.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import integrations


# ---------------------------------------------------------------------------
# _join_integration_url unit tests
# ---------------------------------------------------------------------------

WEBHOOK_BASE = "https://discord.com/api/webhooks/123/tokentokentoken"


def test_join_integration_url():
    for base, path, expected in (
        # Bare "/" must not grow a trailing slash: Discord webhooks 404 on it (#5138).
        (WEBHOOK_BASE + "/", "/", WEBHOOK_BASE),
        (WEBHOOK_BASE, "", WEBHOOK_BASE),
        ("http://host/base", "/v1/me", "http://host/base/v1/me"),
        # A trailing slash inside a non-empty path is preserved (linkding's /api/tags/).
        ("http://host", "/api/tags/", "http://host/api/tags/"),
    ):
        assert integrations._join_integration_url(base, path) == expected, (base, path)


# ---------------------------------------------------------------------------
# Behavioral test through execute_api_call
# ---------------------------------------------------------------------------

DISCORD_INTEGRATION = {
    "id": "discord_test",
    "name": "Discord Webhook",
    "enabled": True,
    "base_url": WEBHOOK_BASE,
    "auth_type": "none",
    "api_key": "",
    "auth_header": "",
    "auth_param": "",
    "description": "",
    "preset": "discord_webhook",
}


@pytest.mark.asyncio
async def test_api_call_root_path_has_no_trailing_slash():
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.headers = {"content-type": "text/plain"}
    mock_resp.text = ""

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(return_value=mock_resp)

    with (
        patch.object(integrations, "_find_integration", return_value=DISCORD_INTEGRATION),
        patch("src.url_safety._default_resolver", return_value=["93.184.216.34"]),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await integrations.execute_api_call(
            "discord_test", "POST", "/", body={"content": "test"}
        )

    assert result.get("exit_code") == 0
    requested_url = mock_client.request.call_args.args[1]
    assert requested_url == WEBHOOK_BASE
