from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_EMAIL_ROUTES = _REPO / "routes" / "email" / "email_routes.py"
_EMAIL_MCP_SERVER = _REPO / "mcp_servers" / "email_server.py"
_EMAIL_FIXTURE_HELPER = _REPO / "scripts" / "ody_eval_email_fixture.py"


def test_fixture_email_requires_explicit_eval_flag():
    """A leftover fixture file must not replace a user's real mailbox.

    The deterministic fixture mailbox is useful for evals, but production
    routes and MCP tools must not activate it merely because
    data/fixture_email_messages.json exists.
    """
    routes = _EMAIL_ROUTES.read_text(encoding="utf-8")
    mcp = _EMAIL_MCP_SERVER.read_text(encoding="utf-8")
    helper = _EMAIL_FIXTURE_HELPER.read_text(encoding="utf-8")

    guard = 'os.environ.get("ODYSSEUS_EMAIL_FIXTURE") == "1" and _fixture_email_file().exists()'
    assert guard in routes
    assert guard in mcp
    assert 'old_fixture_env = os.environ.get("ODYSSEUS_EMAIL_FIXTURE")' in helper
    assert 'os.environ["ODYSSEUS_EMAIL_FIXTURE"] = "1"' in helper
    assert 'os.environ.pop("ODYSSEUS_EMAIL_FIXTURE", None)' in helper
