"""Regression tests for issues found during code review."""

import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.preset_manager import PresetManager
from tests.helpers.import_state import clear_module, preserve_import_state

# Stub `core` packages keep the real search path so submodules a test does not
# stub (core.atomic_io, core.constants) still import for real.
_CORE_PATH = [str(Path(__file__).resolve().parents[1] / "core")]


async def _execute_without_run_context(execute_tool_block, *args, **kwargs):
    from src.tool_execution import NO_TOOL_SECURITY_CONTEXT
    from tests.runtime_evidence_helpers import server_authorized_executor

    kwargs.setdefault("security_context", NO_TOOL_SECURITY_CONTEXT)
    return await server_authorized_executor(execute_tool_block)(*args, **kwargs)


class _FakeColumn:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return ("eq", self.name, value)


class _FakeModelEndpoint:
    id = _FakeColumn("id")
    is_enabled = _FakeColumn("is_enabled")
    owner = _FakeColumn("owner")


class _FakeDbSession:
    id = _FakeColumn("id")
    endpoint_url = _FakeColumn("endpoint_url")


class _FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *conditions):
        for condition in conditions:
            if isinstance(condition, tuple) and condition[0] == "eq":
                _, field, value = condition
                self.rows = [row for row in self.rows if getattr(row, field) == value]
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return _FakeQuery(self.rows)

    def close(self):
        pass


def _install_model_route_import_stubs(monkeypatch):
    core_mod = types.ModuleType("core")
    core_mod.__path__ = _CORE_PATH
    db_mod = types.ModuleType("core.database")
    db_mod.SessionLocal = lambda: _FakeDb([])
    db_mod.ModelEndpoint = _FakeModelEndpoint
    db_mod.Session = _FakeDbSession
    db_mod.Document = MagicMock()
    db_mod.DocumentVersion = MagicMock()
    db_mod.GalleryImage = MagicMock()
    middleware_mod = types.ModuleType("core.middleware")
    middleware_mod.require_admin = lambda request: None
    multipart_mod = types.ModuleType("python_multipart")
    multipart_mod.__version__ = "0.0.13"
    models_mod = types.ModuleType("core.models")
    models_mod.ChatMessage = MagicMock()
    exceptions_mod = types.ModuleType("core.exceptions")
    exceptions_mod.SessionNotFoundError = type("SessionNotFoundError", (Exception,), {})
    session_mgr_mod = types.ModuleType("core.session_manager")
    session_mgr_mod.SessionManager = MagicMock()

    monkeypatch.delitem(sys.modules, "routes.model_routes", raising=False)
    monkeypatch.delitem(sys.modules, "routes.chat_routes", raising=False)
    monkeypatch.delitem(sys.modules, "routes.session_routes", raising=False)
    monkeypatch.setitem(sys.modules, "core", core_mod)
    monkeypatch.setitem(sys.modules, "core.database", db_mod)
    monkeypatch.setitem(sys.modules, "core.middleware", middleware_mod)
    monkeypatch.setitem(sys.modules, "python_multipart", multipart_mod)
    monkeypatch.setitem(sys.modules, "core.models", models_mod)
    monkeypatch.setitem(sys.modules, "core.exceptions", exceptions_mod)
    monkeypatch.setitem(sys.modules, "core.session_manager", session_mgr_mod)


def _default_chat_for(monkeypatch, endpoint, user, *, is_admin=False):
    """Call /api/default-chat as `user` with `endpoint` as the only stored row."""
    _install_model_route_import_stubs(monkeypatch)
    import routes.model_routes as model_routes
    import routes.prefs_routes as prefs_routes

    def scoped_owner_filter(query, model_cls, owner, *, include_shared=True):
        query.rows = [
            row for row in query.rows
            if row.owner == owner or (include_shared and row.owner is None)
        ]
        return query

    monkeypatch.setattr(model_routes, "ModelEndpoint", _FakeModelEndpoint)
    monkeypatch.setattr(model_routes, "SessionLocal", lambda: _FakeDb([endpoint]))
    monkeypatch.setattr(model_routes, "_load_settings", lambda: {})
    monkeypatch.setattr(model_routes, "owner_filter", scoped_owner_filter)
    monkeypatch.setattr(model_routes, "_normalize_base", lambda base: base.rstrip("/"))
    monkeypatch.setattr(model_routes, "build_chat_url", lambda base: f"{base}/chat/completions")
    monkeypatch.setattr(prefs_routes, "_load_for_user", lambda owner: {})

    router = model_routes.setup_model_routes(model_discovery=None)
    route = next(r for r in router.routes if getattr(r, "path", "") == "/api/default-chat")
    request = SimpleNamespace(
        state=SimpleNamespace(current_user=user),
        app=SimpleNamespace(state=SimpleNamespace(
            auth_manager=SimpleNamespace(is_admin=lambda name: is_admin)
        )),
    )
    return route.endpoint(request)


def _import_chat_helpers(monkeypatch):
    for mod_name in [
        "starlette.middleware",
        "starlette.middleware.base",
        "core.models",
        "core.database",
        "routes.prefs_routes",
        "routes.research.research_routes",
        "src.llm_core",
        "src.context_compactor",
        "src.model_context",
        "src.auth_helpers",
    ]:
        if mod_name not in sys.modules:
            monkeypatch.setitem(sys.modules, mod_name, MagicMock())
    return importlib.import_module("routes.chat_helpers")


def _install_core_auth_stub(monkeypatch, *, is_admin, is_configured=True):
    """Install the narrow auth surface needed by tool-policy tests."""
    core_mod = types.ModuleType("core")
    core_mod.__path__ = _CORE_PATH
    auth_mod = types.ModuleType("core.auth")
    auth_mod.AuthManager = lambda: SimpleNamespace(
        is_configured=is_configured, is_admin=lambda username: is_admin,
    )
    core_mod.auth = auth_mod
    monkeypatch.setitem(sys.modules, "core", core_mod)
    monkeypatch.setitem(sys.modules, "core.auth", auth_mod)


def _install_core_middleware_stub(monkeypatch):
    """Install the narrow middleware surface needed by loopback tool tests."""
    core_mod = types.ModuleType("core")
    core_mod.__path__ = _CORE_PATH
    middleware_mod = types.ModuleType("core.middleware")
    middleware_mod.INTERNAL_TOOL_HEADER = "X-Internal-Tool"
    middleware_mod.INTERNAL_TOOL_TOKEN = "test-token"
    core_mod.middleware = middleware_mod
    monkeypatch.setitem(sys.modules, "core", core_mod)
    monkeypatch.setitem(sys.modules, "core.middleware", middleware_mod)
    return middleware_mod


def test_providers_requires_admin_before_discovery_and_cache(monkeypatch):
    _install_model_route_import_stubs(monkeypatch)
    import routes.model_routes as model_routes

    class _Discovery:
        def __init__(self):
            self.calls = 0

        def get_providers(self):
            self.calls += 1
            return {"providers": [{"host": "internal.example"}]}

    discovery = _Discovery()
    router = model_routes.setup_model_routes(discovery)
    endpoint = next(
        route.endpoint
        for route in router.routes
        if getattr(route, "path", "") == "/api/providers"
    )
    request = SimpleNamespace()

    assert endpoint(request, refresh=True) == {"providers": [{"host": "internal.example"}]}
    assert discovery.calls == 1

    def deny_admin(_request):
        raise PermissionError("admin required")

    monkeypatch.setattr(model_routes, "require_admin", deny_admin)

    with pytest.raises(PermissionError):
        endpoint(request, refresh=True)
    with pytest.raises(PermissionError):
        endpoint(request, refresh=False)
    assert discovery.calls == 1


def test_default_chat_does_not_auto_pick_shared_endpoint_for_fresh_user(monkeypatch):
    shared_ep = SimpleNamespace(
        id="shared",
        base_url="http://localhost:11434",
        is_enabled=True,
        owner=None,
        cached_models='["shared-model"]',
    )

    assert _default_chat_for(monkeypatch, shared_ep, "fresh") == {
        "endpoint_id": "",
        "endpoint_url": "",
        "model": "",
    }


def test_default_chat_uses_owned_endpoint_as_regular_user_last_resort(monkeypatch):
    owned_ep = SimpleNamespace(
        id="owned",
        base_url="http://localhost:11434",
        is_enabled=True,
        owner="fresh",
        cached_models='["owned-model"]',
    )

    assert _default_chat_for(monkeypatch, owned_ep, "fresh") == {
        "endpoint_id": "owned",
        "endpoint_url": "http://localhost:11434/chat/completions",
        "model": "owned-model",
    }


def test_preset_manager_persists_inject_fields(tmp_path):
    manager = PresetManager(str(tmp_path / "presets.json"))

    ok = manager.update_custom(
        temperature=0.7,
        max_tokens=2048,
        system_prompt="Be useful.",
        name="Custom",
        enabled=True,
        inject_prefix="PREFIX",
        inject_suffix="SUFFIX",
    )

    assert ok is True
    assert manager.presets["custom"]["inject_prefix"] == "PREFIX"
    assert manager.presets["custom"]["inject_suffix"] == "SUFFIX"

    reloaded = PresetManager(str(tmp_path / "presets.json"))
    assert reloaded.presets["custom"]["inject_prefix"] == "PREFIX"
    assert reloaded.presets["custom"]["inject_suffix"] == "SUFFIX"


def test_preset_manager_default_custom_preset_starts_disabled(tmp_path):
    manager = PresetManager(str(tmp_path / "presets.json"))

    custom = manager.presets["custom"]

    assert custom["enabled"] is False
    assert custom["system_prompt"] == ""
    assert custom["temperature"] == 1.0
    assert custom["max_tokens"] == 32768


def test_preset_manager_migrates_legacy_default_custom_preset_disabled(tmp_path):
    presets_file = tmp_path / "presets.json"
    presets_file.write_text(
        json.dumps({
            "custom": {
                "name": "Custom",
                "temperature": 0.7,
                "max_tokens": 4096,
                "system_prompt": "You are a helpful, balanced assistant. Match your response style to the user's needs.",
            }
        }),
        encoding="utf-8",
    )

    manager = PresetManager(str(tmp_path / "presets.json"))
    custom = manager.presets["custom"]

    assert custom["enabled"] is False
    assert custom["system_prompt"] == ""
    assert custom["temperature"] == 1.0
    assert custom["max_tokens"] == 32768


def test_normalize_thinking_handles_lowercase_thinking_process(monkeypatch):
    chat_helpers = _import_chat_helpers(monkeypatch)

    text = (
        "Thinking process:\n"
        "Analyze the Request: The user is explicitly instructing me to use the tag.\n\n"
        "hi"
    )

    normalized = chat_helpers._normalize_thinking(text)

    assert normalized == (
        "<think>Analyze the Request: The user is explicitly instructing me to use the tag.</think>\n\n"
        "hi"
    )


@pytest.mark.asyncio
async def test_build_chat_context_incognito_disables_skills_and_does_not_duplicate_user_message(monkeypatch):
    chat_helpers = _import_chat_helpers(monkeypatch)
    chat_helpers._INCOGNITO_CONTEXTS.clear()

    async def fake_preprocess(chat_handler, message, att_ids, sess, **kwargs):
        # **kwargs absorbs auto_opened_docs (added when PDF imports auto-create
        # docs) and any other future preprocess kwargs without the test fixture
        # having to be updated each time.
        return chat_helpers.PreprocessedMessage(
            enhanced_message=message,
            user_content=message,
            text_for_context=message,
            youtube_transcripts=[],
            attachment_meta=[],
        )

    def fake_extract_preset(chat_handler, preset_id):
        return chat_helpers.PresetInfo(
            temperature=0.7,
            max_tokens=1024,
            system_prompt=None,
            character_name=None,
        )

    def fake_add_user_message(sess, chat_handler, preprocessed, incognito=False):
        sess.messages.append({"role": "user", "content": preprocessed.user_content})

    async def fake_maybe_compact(sess, endpoint_url, model, messages, headers, owner=None):
        return messages, 123, False

    monkeypatch.setattr(chat_helpers, "preprocess", fake_preprocess)
    monkeypatch.setattr(chat_helpers, "extract_preset", fake_extract_preset)
    monkeypatch.setattr(chat_helpers, "add_user_message", fake_add_user_message)
    monkeypatch.setattr(chat_helpers, "load_prefs_for_user", lambda user: {})
    monkeypatch.setattr(chat_helpers, "effective_user", lambda request: "tester")
    monkeypatch.setattr(chat_helpers, "normalize_model_id", lambda endpoint_url, model, **kwargs: None)
    monkeypatch.setattr(chat_helpers, "maybe_compact", fake_maybe_compact)
    monkeypatch.setattr(chat_helpers, "trim_for_context", lambda messages, context_length: messages)

    sess = SimpleNamespace(
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        headers={},
        messages=[],
        get_context_messages=lambda: list(sess.messages),
    )
    request = SimpleNamespace()
    chat_handler = SimpleNamespace()
    preface_options = {}

    def fake_build_context_preface(**kwargs):
        preface_options.update(kwargs)
        return [], [], []

    chat_processor = SimpleNamespace(build_context_preface=fake_build_context_preface)

    ctx = await chat_helpers.build_chat_context(
        sess=sess,
        request=request,
        chat_handler=chat_handler,
        chat_processor=chat_processor,
        message="hello",
        session_id="s1",
        incognito=True,
    )

    user_messages = [m for m in ctx.messages if m.get("role") == "user" and m.get("content") == "hello"]
    assert len(user_messages) == 1
    assert preface_options["use_skills"] is False


@pytest.mark.asyncio
async def test_build_chat_context_incognito_ignores_saved_session_history(monkeypatch):
    chat_helpers = _import_chat_helpers(monkeypatch)
    chat_helpers._INCOGNITO_CONTEXTS.clear()

    async def fake_preprocess(chat_handler, message, att_ids, sess, **kwargs):
        return chat_helpers.PreprocessedMessage(
            enhanced_message=message,
            user_content=message,
            text_for_context=message,
            youtube_transcripts=[],
            attachment_meta=[],
        )

    async def fake_maybe_compact(sess, endpoint_url, model, messages, headers, owner=None):
        return messages, 123, False

    monkeypatch.setattr(chat_helpers, "preprocess", fake_preprocess)
    monkeypatch.setattr(chat_helpers, "extract_preset", lambda *_args, **_kwargs: chat_helpers.PresetInfo(0.7, 1024, None, None))
    monkeypatch.setattr(chat_helpers, "load_prefs_for_user", lambda user: {})
    monkeypatch.setattr(chat_helpers, "effective_user", lambda request: "tester")
    monkeypatch.setattr(chat_helpers, "normalize_model_id", lambda endpoint_url, model, **kwargs: None)
    monkeypatch.setattr(chat_helpers, "maybe_compact", fake_maybe_compact)
    monkeypatch.setattr(chat_helpers, "trim_for_context", lambda messages, context_length: messages)

    sess = SimpleNamespace(
        endpoint_url="http://localhost:8000/v1",
        model="test-model",
        headers={},
        get_context_messages=lambda: [{"role": "user", "content": "older non-incognito secret"}],
    )
    chat_processor = SimpleNamespace(build_context_preface=lambda **kwargs: ([], [], []))

    ctx = await chat_helpers.build_chat_context(
        sess=sess,
        request=SimpleNamespace(),
        chat_handler=SimpleNamespace(),
        chat_processor=chat_processor,
        message="fresh incognito turn",
        session_id="s-incog",
        incognito=True,
    )

    assert {"role": "user", "content": "fresh incognito turn"} in ctx.messages
    assert all(m.get("content") != "older non-incognito secret" for m in ctx.messages)


@pytest.mark.asyncio
async def test_admin_agent_tools_require_admin(monkeypatch):
    _install_core_auth_stub(monkeypatch, is_admin=False)
    from src.tool_execution import execute_tool_block


    for tool_name in ("manage_tokens", "app_api", "serve_preset"):
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type=tool_name, content='{"action":"create","name":"bad"}'),
            owner="regular-user",
        )

        assert desc == f"{tool_name}: BLOCKED"
        assert result["exit_code"] == 1
        assert "requires an admin" in result["error"]


@pytest.mark.asyncio
async def test_host_shell_uses_tui_bridge_context(monkeypatch):
    _install_core_auth_stub(monkeypatch, is_admin=True)
    from src.tool_execution import execute_tool_block
    import src.agent_tools.subprocess_tools as subprocess_tools

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"stdout": "ajax 192.168.1.42", "stderr": "", "exit_code": 0}

    calls = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            calls.append(("init", args, kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def post(self, url, **kwargs):
            calls.append(("post", url, kwargs))
            return FakeResponse()

    monkeypatch.setattr(subprocess_tools.httpx, "AsyncClient", FakeAsyncClient)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(
            tool_type="host_shell",
            content=json.dumps({"command": "ip neigh", "timeout": 12}),
        ),
        owner="admin",
        client_runtime_context={
            "surface": "odysseus-tui",
            "host_shell_bridge": {
                "url": "http://host.docker.internal:17654/run",
                "token": "bridge-token",
            }
        },
    )

    assert desc.startswith("host_shell:")
    assert result["exit_code"] == 0
    assert result["output"] == "ajax 192.168.1.42"
    assert calls[1][1] == "http://host.docker.internal:17654/run"
    bridge_payload = calls[1][2]["json"]
    assert bridge_payload["command"] == "ip neigh"
    assert bridge_payload["timeout"] == 12
    assert isinstance(bridge_payload["request_id"], str)
    assert bridge_payload["request_id"]
    assert calls[1][2]["headers"]["X-Odysseus-TUI-Bridge-Token"] == "bridge-token"


@pytest.mark.asyncio
async def test_host_shell_forwards_detach_and_job_polling(monkeypatch):
    _install_core_auth_stub(monkeypatch, is_admin=True)
    from src.tool_execution import execute_tool_block
    import src.agent_tools.subprocess_tools as subprocess_tools

    responses = iter([
        {"stdout": "started", "stderr": "", "exit_code": 0, "detached": True, "job_id": "job-1"},
        {"stdout": "still running", "stderr": "", "exit_code": 0, "status": "running", "job_id": "job-1"},
    ])
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return next(responses)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr(subprocess_tools.httpx, "AsyncClient", FakeAsyncClient)
    context = {
        "surface": "odysseus-tui",
        "host_shell_bridge": {"url": "http://host.docker.internal:17654/run", "token": "bridge-token"},
    }

    _, started = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="host_shell", content=json.dumps({"command": "sleep 5", "detach": True})),
        owner="admin", client_runtime_context=context,
    )
    _, running = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="host_shell", content=json.dumps({"job_id": "job-1"})),
        owner="admin", client_runtime_context=context,
    )

    assert started["detached"] is True
    assert started["job_id"] == "job-1"
    assert running["status"] == "running"
    assert calls == [
        {"command": "sleep 5", "timeout": 30, "detach": True},
        {"job_id": "job-1", "timeout": 30},
    ]


@pytest.mark.asyncio
async def test_host_shell_rejects_non_local_bridge_url_before_http(monkeypatch):
    _install_core_auth_stub(monkeypatch, is_admin=True)
    from src.tool_execution import execute_tool_block
    import src.agent_tools.subprocess_tools as subprocess_tools

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("host_shell should reject unsafe bridge URL before HTTP")

    monkeypatch.setattr(subprocess_tools.httpx, "AsyncClient", UnexpectedAsyncClient)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(
            tool_type="host_shell",
            content=json.dumps({"command": "ip neigh", "timeout": 12}),
        ),
        owner="admin",
        client_runtime_context={
            "host_shell_bridge": {
                "url": "http://169.254.169.254/run",
                "token": "bridge-token",
            }
        },
    )

    assert desc.startswith("host_shell:")
    assert result["exit_code"] == 1
    assert result.get("failure_kind") == "resource_identity_denied"
    assert "unresolved" in result["error"].lower()


def test_host_shell_bridge_allows_backend_default_gateway(monkeypatch):
    import src.agent_tools.subprocess_tools as subprocess_tools

    monkeypatch.setattr(
        subprocess_tools,
        "_docker_default_gateway_ips",
        lambda: {"172.18.0.1"},
    )

    assert subprocess_tools.is_host_shell_bridge_url_allowed(
        "http://172.18.0.1:17654/run"
    )
    assert not subprocess_tools.is_host_shell_bridge_url_allowed(
        "http://172.18.0.2:17654/run"
    )


@pytest.mark.asyncio
async def test_app_api_blocks_shell_routes_before_loopback(monkeypatch):
    import httpx
    from src.tool_implementations import do_app_api

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("app_api should block shell routes before loopback")

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedAsyncClient)

    for path in ("/api/shell/exec", "api/shell/stream"):
        result = await do_app_api(
            json.dumps(
                {
                    "action": "call",
                    "method": "POST",
                    "path": path,
                    "body": {"command": "echo should-not-run"},
                }
            ),
            owner="admin",
        )

        assert result["exit_code"] == 1
        assert "Path blocked for safety" in result["error"]
        assert "Sensitive endpoints" in result["error"]


@pytest.mark.asyncio
async def test_app_api_blocks_cookbook_host_control_routes_before_loopback(monkeypatch):
    import httpx
    from src.tool_implementations import do_app_api

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("app_api should block host-control routes before loopback")

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedAsyncClient)

    blocked_calls = (
        (
            "api/cookbook/packages/install",
            {"pip": "hf_transfer"},
            "package installation is host code execution",
        ),
        (
            "/api/cookbook/rebuild-engine",
            {"engine": "llamacpp"},
            "engine rebuild mutates local or remote host state",
        ),
        (
            "/api/cookbook/kill-pid",
            {"pid": 12345, "signal": "TERM"},
            "process signalling is host control",
        ),
    )

    for path, body, error_text in blocked_calls:
        result = await do_app_api(
            json.dumps(
                {
                    "action": "call",
                    "method": "POST",
                    "path": path,
                    "body": body,
                }
            ),
            owner="admin",
        )

        assert result["exit_code"] == 1
        assert error_text in result["error"]


@pytest.mark.asyncio
async def test_app_api_blocks_search_route_before_loopback(monkeypatch):
    import httpx
    from src.tool_implementations import do_app_api

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("app_api should block search routes before loopback")

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedAsyncClient)

    result = await do_app_api(
        json.dumps(
            {
                "action": "call",
                "method": "GET",
                "path": "/api/search",
                "query": {"q": "crow box designs"},
            }
        ),
        owner="admin",
    )

    assert result["exit_code"] == 1
    assert "use the `web_search` tool" in result["error"]


@pytest.mark.asyncio
async def test_app_api_endpoint_discovery_hides_shell_and_host_control_routes(monkeypatch):
    _install_core_middleware_stub(monkeypatch)
    import httpx
    from src.tool_implementations import do_app_api

    class FakeResponse:
        def json(self):
            return {
                "paths": {
                    "/api/shell/exec": {"post": {"summary": "Execute Shell Command"}},
                    "/api/shell/stream": {"post": {"summary": "Stream Shell Command"}},
                    "/api/auth/settings": {"get": {"summary": "Auth Settings"}},
                    "/api/cookbook/packages": {"get": {"summary": "List Cookbook Packages"}},
                    "/api/cookbook/packages/install": {"post": {"summary": "Install Package"}},
                    "/api/cookbook/rebuild-engine": {"post": {"summary": "Rebuild Engine"}},
                    "/api/cookbook/kill-pid": {"post": {"summary": "Kill Process"}},
                    "/api/cookbook/gpus": {"get": {"summary": "List GPUs"}},
                }
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = await do_app_api(json.dumps({"action": "endpoints"}), owner="admin")

    assert result["exit_code"] == 0
    paths = {(endpoint["method"], endpoint["path"]) for endpoint in result["endpoints"]}
    assert paths == {("GET", "/api/cookbook/packages"), ("GET", "/api/cookbook/gpus")}


@pytest.mark.asyncio
async def test_public_agent_policy_blocks_sensitive_tools(monkeypatch, tmp_path):
    _install_core_auth_stub(monkeypatch, is_admin=False)
    from src.tool_execution import execute_tool_block
    import src.tool_execution as tool_execution
    mcp = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)


    # Every bare email tool name is spelled out (not imported from
    # BUILTIN_EMAIL_TOOLS) so accidentally dropping one from that set fails
    # here instead of silently shrinking the blocklist.
    bare_email_tools = (
        "list_email_accounts", "list_emails", "read_email", "search_emails",
        "scan_email_unsubscribes", "unsubscribe_email",
        "send_email", "reply_to_email", "draft_email", "draft_email_reply",
        "ai_draft_email_reply", "archive_email", "delete_email",
        "mark_email_read", "bulk_email", "download_attachment",
    )
    test_file = tmp_path / "test.txt"
    test_file.write_text("sample")
    for tool_name in bare_email_tools + ("read_file", "mcp__email__send_email"):
        content = json.dumps({"path": str(test_file)}) if tool_name == "read_file" else "{}"
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type=tool_name, content=content),
            owner="regular-user",
            workspace=str(tmp_path),
        )
        assert desc == f"{tool_name}: BLOCKED"
        assert result["exit_code"] == 1
        assert "restricted to admin users" in result["error"]


@pytest.mark.asyncio
async def test_disabled_qualified_email_tool_blocks_bare_alias(monkeypatch):
    """A bare email fence is an alias for its mcp__email__ form. Plan mode and
    the MCP settings toggle write the QUALIFIED name into disabled_tools, so
    the gate must block the bare spelling too — and never reach the MCP
    manager (PR #3681 review follow-up)."""
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block, NO_TOOL_SECURITY_CONTEXT
    from src.turn_contract import canonical_tool
    from src.agent_runtime.authority import RequestAuthority, OperationGrant

    def fail_get_mcp_manager():
        raise AssertionError("blocked email tool must not reach the MCP manager")

    monkeypatch.setattr(tool_execution, "get_mcp_manager", fail_get_mcp_manager)

    for bare, disabled in (
        # qualified denylist entry blocks the bare alias…
        ("list_emails", {"mcp__email__list_emails"}),
        ("download_attachment", {"mcp__email__download_attachment"}),
        # …and a bare denylist entry blocks the qualified spelling.
        ("mcp__email__delete_email", {"delete_email"}),
    ):
        canon = canonical_tool(bare)
        auth = RequestAuthority("test", "admin-user", "", "", (OperationGrant(canon),), backend_resources=())
        desc, result = await execute_tool_block(
            SimpleNamespace(tool_type=bare, content="{}"),
            owner="admin-user",
            disabled_tools=disabled,
            request_authority=auth,
            security_context=NO_TOOL_SECURITY_CONTEXT,
        )
        assert desc == f"{bare}: BLOCKED"
        assert result["exit_code"] == 1
        assert "disabled by user" in result["error"]


@pytest.mark.asyncio
async def test_tool_policy_qualified_email_block_covers_bare_alias(monkeypatch):
    """Same aliasing rule for the turn ToolPolicy denylist."""
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block, NO_TOOL_SECURITY_CONTEXT
    from src.tool_policy import ToolPolicy
    from src.agent_runtime.authority import RequestAuthority, OperationGrant

    def fail_get_mcp_manager():
        raise AssertionError("blocked email tool must not reach the MCP manager")

    monkeypatch.setattr(tool_execution, "get_mcp_manager", fail_get_mcp_manager)

    policy = ToolPolicy(disabled_tools=frozenset({"mcp__email__send_email"}))
    auth = RequestAuthority("test", "admin-user", "", "", (OperationGrant("send_email"),), backend_resources=())
    desc, result = await execute_tool_block(
        SimpleNamespace(tool_type="send_email", content="{}"),
        owner="admin-user",
        tool_policy=policy,
        request_authority=auth,
        security_context=NO_TOOL_SECURITY_CONTEXT,
    )
    assert desc == "send_email: BLOCKED"
    assert result["exit_code"] == 1


@pytest.mark.asyncio
async def test_disable_tool_email_covers_full_builtin_set(monkeypatch):
    """The friendly `disable_tool email` toggle must cover every built-in
    email tool, in BOTH spellings — bare names (function-schema hiding,
    bare-fence dispatch) and mcp__email__* (MCP schema hiding, runtime
    qualified blocks). Hand-picking a subset left tools like delete_email
    and download_attachment enabled (PR #3681 review follow-up)."""
    # Import first so the module loads against the real core package; only
    # the call-time SessionLocal import below sees the stub.
    from src.tool_implementations import do_manage_settings
    import src.settings as settings_mod

    db_mod = types.ModuleType("core.database")

    class _Db:
        def close(self):
            pass

    db_mod.SessionLocal = lambda: _Db()
    monkeypatch.setitem(sys.modules, "core.database", db_mod)

    store = {}

    def fake_load_settings():
        return dict(store)

    def fake_save_settings(s):
        store.clear()
        store.update(s)

    monkeypatch.setattr(settings_mod, "load_settings", fake_load_settings)
    monkeypatch.setattr(settings_mod, "save_settings", fake_save_settings)

    result = await do_manage_settings(
        '{"action": "disable_tool", "tool": "email"}', owner="admin"
    )

    assert result["exit_code"] == 0
    disabled = set(store["disabled_tools"])
    # Spelled out (not imported from BUILTIN_EMAIL_TOOLS) so dropping a name
    # from the constant fails here instead of silently shrinking the toggle.
    bare_email_tools = (
        "list_email_accounts", "list_emails", "read_email", "search_emails",
        "scan_email_unsubscribes", "unsubscribe_email",
        "send_email", "reply_to_email", "draft_email", "draft_email_reply",
        "ai_draft_email_reply", "archive_email", "delete_email",
        "mark_email_read", "bulk_email", "download_attachment",
    )
    for tool_name in bare_email_tools:
        assert tool_name in disabled, tool_name
        assert f"mcp__email__{tool_name}" in disabled, tool_name

    # enable_tool email must remove the full set again.
    result = await do_manage_settings(
        '{"action": "enable_tool", "tool": "email"}', owner="admin"
    )
    assert result["exit_code"] == 0
    assert store["disabled_tools"] == []


class _FakeMcpManager:
    def __init__(self):
        self.calls = []

    def resource_identity(self, qualified_name):
        from src.agent_runtime.resources import ExternalResource
        server = qualified_name.split("__")[1] if "__" in qualified_name else "email"
        return ExternalResource("mcp", f"mcp:{server}", server, qualified_name, "fake-incarnation")

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return {"output": "ok", "exit_code": 0}


@pytest.mark.asyncio
async def test_bare_email_dispatch_rejects_non_object_json_args(monkeypatch):
    """The fence parser accepts JSON arrays as inline args, but email tools
    take objects — a correctable error must come back instead of a silent
    empty-args call (same class as #3966)."""
    _install_core_auth_stub(monkeypatch, is_admin=True)
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    mcp = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="bulk_email", content='["10", "11"]'),
        owner="admin-user",
    )
    assert result["exit_code"] == 1
    assert "JSON object" in result["error"]
    assert mcp.calls == [], "non-object args must never reach the MCP server"


@pytest.mark.asyncio
async def test_bare_email_dispatch_rejects_invalid_json_body(monkeypatch):
    """The classic tag/body form reaches execution unvalidated (only INLINE
    args are JSON-checked by the parser). A non-JSON-object body must return a
    correctable parse error — silently becoming {} args would read the DEFAULT
    mailbox instead of the one the model meant. Covers both the brace-looking
    `{account: "work"}` and the bare `account: work` shapes."""
    _install_core_auth_stub(monkeypatch, is_admin=True)
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    for bad_body in ('{account: "work"}', "account: work"):
        mcp = _FakeMcpManager()
        monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type="list_emails", content=bad_body),
            owner="admin-user",
        )
        assert result["exit_code"] == 1, bad_body
        assert "not valid JSON" in result["error"], bad_body
        assert mcp.calls == [], f"malformed args must never reach MCP: {bad_body!r}"


@pytest.mark.asyncio
async def test_legacy_mcp_tools_decode_inline_json_args(monkeypatch):
    """The relaxed parser accepts inline JSON for non-code tags, but the legacy
    line-based arg builders (web_search/web_fetch/read_file/write_file/
    generate_image) would wrap the whole JSON string as the query/path/prompt.
    A JSON object carrying the tool's primary key must be used directly."""
    from src.tool_execution import _build_mcp_args

    cases = {
        "web_search": ('{"query": "odysseus pr 3681"}', {"query": "odysseus pr 3681"}),
        "web_fetch": ('{"url": "https://example.com"}', {"url": "https://example.com"}),
        "read_file": ('{"path": "/tmp/x.txt"}', {"path": "/tmp/x.txt"}),
        "write_file": ('{"path": "/tmp/x", "content": "hi"}', {"path": "/tmp/x", "content": "hi"}),
        "generate_image": ('{"prompt": "a cat"}', {"prompt": "a cat"}),
    }
    for tool, (content, expected) in cases.items():
        assert _build_mcp_args(tool, content) == expected, tool

    # Freeform (non-JSON) content keeps the line-based behavior.
    assert _build_mcp_args("web_search", "latest python release") == {"query": "latest python release"}
    # A JSON object WITHOUT the tool's primary key is not args — fall back
    # (write_file content the model happened to write as a bare object).
    assert _build_mcp_args("write_file", '{"config": "value"}') == {
        "path": '{"config": "value"}', "content": "",
    }


def test_mcp_json_primary_keys_are_all_live():
    """Every _MCP_JSON_PRIMARY_KEYS entry must be reachable: _build_mcp_args is
    only called from _call_mcp_tool, which only runs for _MCP_TOOL_MAP tools.
    An entry outside _MCP_TOOL_MAP is dead code whose inline-JSON decode never
    executes — manage_memory was exactly that (it routes through
    dispatch_ai_tool), and a unit test on _build_mcp_args passed on the dead
    path while the real call still corrupted. This pins it so it can't recur."""
    from src.tool_execution import _MCP_JSON_PRIMARY_KEYS, _MCP_TOOL_MAP

    dead = set(_MCP_JSON_PRIMARY_KEYS) - set(_MCP_TOOL_MAP)
    assert not dead, f"dead JSON-primary entries (never reach _build_mcp_args): {sorted(dead)}"


@pytest.mark.asyncio
async def test_write_file_inline_json_args(monkeypatch):
    """write_file has no MCP server, so it runs via _direct_fallback ->
    WriteFileTool, NOT _build_mcp_args. Inline JSON must therefore be decoded
    by the handler itself: drive the LIVE path (execute_tool_block, no MCP) and
    assert the file is written to the intended path with the intended content,
    not a file literally named with the JSON blob. A _build_mcp_args unit test
    can't catch this — it's on the dead MCP path for write_file."""
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda t: False)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: None)

    captured = {}

    def fake_resolve(p):
        captured["path"] = p
        raise ValueError("probe-stop-before-disk")

    monkeypatch.setattr(tool_execution, "_resolve_tool_path", fake_resolve)

    from src.tool_parsing import parse_tool_blocks
    blocks = parse_tool_blocks('```write_file {"path": "/tmp/wf.txt", "content": "hi"}\n```')
    for b in blocks:
        await _execute_without_run_context(execute_tool_block, b, owner="admin", workspace="/tmp")

    assert captured.get("path") == "/tmp/wf.txt", (
        f"write_file did not decode inline JSON args; got path {captured.get('path')!r}"
    )


@pytest.mark.asyncio
async def test_write_file_rejects_missing_content_in_legacy_native_shape(monkeypatch, tmp_path):
    """A native call missing schema-required content must not create 0-byte artifacts."""
    import json
    import src.tool_execution as tool_execution
    from src.agent_tools.filesystem_tools import WriteFileTool

    touched = []
    target = tmp_path / "should-not-be-written.html"

    def fake_resolve(path):
        touched.append(path)
        return str(target)

    monkeypatch.setattr(tool_execution, "_resolve_tool_path", fake_resolve)

    # 1. Missing content section in legacy shape is rejected
    result = await WriteFileTool().execute("/workspace/output.html", {})
    assert result["exit_code"] == 1
    assert "content required" in result["error"]
    assert touched == ["/workspace/output.html"]
    assert not target.exists()

    # 2. Missing content in native JSON shape is also rejected
    result_json = await WriteFileTool().execute(json.dumps({"path": "/workspace/output.html"}), {})
    assert result_json["exit_code"] == 1
    assert "content required" in result_json["error"]

    # 3. Positive control: explicit empty body on a new path creates an empty file under Task 3.5/3.7
    result_created = await WriteFileTool().execute("/workspace/output.html\n", {})
    assert result_created["exit_code"] == 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_plan_mode_blocks_mutating_email_aliases_without_mcp_inventory(monkeypatch):
    """Plan-mode safety for bare email aliases must hold from the STATIC
    partition alone — no MCP read-only inventory involved: mutators (the
    draft/download tools included) are blocked before dispatch, while the
    explicitly read-only search_emails goes through."""
    _install_core_auth_stub(monkeypatch, is_admin=True)
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block
    from src.tool_security import plan_mode_disabled_tools

    mcp = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    denied = plan_mode_disabled_tools()

    for tool_name in ("draft_email", "draft_email_reply", "ai_draft_email_reply",
                      "download_attachment", "send_email", "delete_email", "unsubscribe_email"):
        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type=tool_name, content="{}"),
            owner="admin-user",
            disabled_tools=denied,
        )
        assert result["exit_code"] == 1, tool_name
        assert mcp.calls == [], f"{tool_name} reached the MCP server in plan mode"

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="search_emails", content='{"query": "x"}'),
        owner="admin-user",
        disabled_tools=denied,
    )
    assert result["exit_code"] == 0
    assert mcp.calls == [
        ("mcp__email__search_emails", {"query": "x", "_odysseus_owner": "admin-user"}),
    ]

    mcp.calls.clear()
    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="scan_email_unsubscribes", content='{"limit": 1}'),
        owner="admin-user",
        disabled_tools=denied,
    )
    assert result["exit_code"] == 0
    assert mcp.calls == [
        ("mcp__email__scan_email_unsubscribes", {"limit": 1, "_odysseus_owner": "admin-user"}),
    ]


@pytest.mark.asyncio
async def test_bare_email_dispatch_empty_content_calls_with_empty_args(monkeypatch):
    """An empty fence (```list_email_accounts``` with no body) dispatches with
    {} args — the no-arg call shape local models really emit."""
    _install_core_auth_stub(monkeypatch, is_admin=True)
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    mcp = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="list_email_accounts", content=""),
        owner="admin-user",
    )
    assert result["exit_code"] == 0
    assert mcp.calls == [
        ("mcp__email__list_email_accounts", {"_odysseus_owner": "admin-user"}),
    ]


@pytest.mark.asyncio
async def test_email_mcp_non_object_args_fail_before_dispatch(monkeypatch):
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    fake = _FakeMcpManager()
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: fake)

    desc, result = await _execute_without_run_context(
        execute_tool_block,
        SimpleNamespace(tool_type="mcp__email__list_emails", content='["INBOX"]'),
        owner="alice",
    )

    assert desc == "mcp: mcp__email__list_emails"
    assert result["exit_code"] == 1
    assert "JSON object" in result["error"]
    assert fake.calls == []


@pytest.mark.asyncio
async def test_email_mcp_dispatch_includes_hidden_owner(monkeypatch):
    import src.tool_execution as tool_execution
    from src.tool_execution import execute_tool_block

    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    for tool_type, expected_desc in (
        ("mcp__email__list_emails", "mcp: mcp__email__list_emails"),
        ("list_emails", "email: list_emails"),
    ):
        fake = _FakeMcpManager()
        monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: fake)

        desc, result = await _execute_without_run_context(
            execute_tool_block,
            SimpleNamespace(tool_type=tool_type, content='{"folder":"INBOX"}'),
            owner="alice",
        )

        assert desc == expected_desc
        assert result["exit_code"] == 0
        assert fake.calls == [
            ("mcp__email__list_emails", {"folder": "INBOX", "_odysseus_owner": "alice"}),
        ]


def test_public_agent_policy_hides_sensitive_tools(monkeypatch):
    _install_core_auth_stub(monkeypatch, is_admin=False)
    from src.tool_security import blocked_tools_for_owner


    blocked = blocked_tools_for_owner("regular-user")

    assert "send_email" in blocked
    assert "read_file" in blocked
    assert "app_api" in blocked
    assert "serve_preset" in blocked
    assert "manage_tasks" in blocked


def test_presetup_does_not_grant_admin_tools_when_auth_enabled(monkeypatch):
    """Pre-setup window: auth is enabled but no admin user exists yet.

    This must NOT be treated as single-user/admin at the tool layer — the
    server-execution tools (bash/python) stay blocked as defense-in-depth so
    an unauthenticated caller that slips past the auth middleware (e.g. via a
    loopback bypass) can't reach an RCE before setup completes.
    """
    monkeypatch.delenv("AUTH_ENABLED", raising=False)  # default: enabled
    _install_core_auth_stub(monkeypatch, is_admin=False, is_configured=False)


    from src.tool_security import (
        blocked_tools_for_owner,
        owner_is_admin_or_single_user,
    )

    assert owner_is_admin_or_single_user(None) is False
    blocked = blocked_tools_for_owner(None)
    assert "bash" in blocked
    assert "python" in blocked


def test_single_user_mode_keeps_full_tool_access_when_auth_disabled(monkeypatch):
    """Intentional single-user mode (AUTH_ENABLED=false) keeps full tool
    access even with no admin user — this is the default local/self-host UX
    and must not regress."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    _install_core_auth_stub(monkeypatch, is_admin=False, is_configured=False)


    from src.tool_security import (
        blocked_tools_for_owner,
        owner_is_admin_or_single_user,
    )

    assert owner_is_admin_or_single_user(None) is True
    assert blocked_tools_for_owner(None) == set()


def test_auth_disabled_configured_mode_keeps_full_tool_access(monkeypatch):
    """AUTH_ENABLED=false is still intentional single-user mode after setup.

    Once an admin account exists, AuthManager.is_configured becomes true. The
    tool gate must still honor explicit auth-disabled mode before requiring an
    owner/admin match, otherwise agent mode hides email/MCP/local tools from the
    operator.
    """
    monkeypatch.setenv("AUTH_ENABLED", "false")
    _install_core_auth_stub(monkeypatch, is_admin=False)


    from src.tool_security import (
        blocked_tools_for_owner,
        owner_is_admin_or_single_user,
    )

    assert owner_is_admin_or_single_user(None) is True
    assert blocked_tools_for_owner(None) == set()


@pytest.mark.asyncio
async def test_webhook_tool_reuses_private_url_validation(monkeypatch):
    class FakeDb:
        def close(self):
            pass

    from core.database import utcnow_naive

    fake_core_db = types.ModuleType("core.database")
    fake_core_db.SessionLocal = lambda: FakeDb()
    fake_core_db.Webhook = object
    fake_core_db.utcnow_naive = utcnow_naive
    fake_src_db = types.ModuleType("src.database")
    fake_src_db.SessionLocal = fake_core_db.SessionLocal
    fake_src_db.Webhook = object
    # Re-import src.webhook_manager against the fake database, then put the
    # real module back so sibling tests do not inherit `Webhook = object`.
    with preserve_import_state("src.webhook_manager"):
        clear_module("src.webhook_manager")
        with monkeypatch.context() as patch:
            patch.setitem(sys.modules, "core.database", fake_core_db)
            patch.setitem(sys.modules, "src.database", fake_src_db)
            from src.agent_tools.admin_tools import do_manage_webhooks

            result = await do_manage_webhooks(
                '{"action":"add","url":"http://127.0.0.1:8000/hook","events":"chat.completed"}',
                owner="admin",
            )

    assert result["exit_code"] == 1
    assert "private/internal" in result["error"]


def test_default_chat_fallback_skips_hidden_models(monkeypatch):
    """With no default model set, the fallback picks the first visible cached model."""
    for user, is_admin, owner, cached, hidden, expected in (
        ("fresh", False, "fresh", ["hidden-model", "visible-model"], ["hidden-model"], "visible-model"),
        ("admin", True, None, ["hidden-model", "visible-model"], ["hidden-model"], "visible-model"),
        ("admin", True, None, ["hidden-a", "hidden-b"], ["hidden-a", "hidden-b"], ""),
    ):
        endpoint = SimpleNamespace(
            id="ep1",
            base_url="http://localhost:11434",
            is_enabled=True,
            owner=owner,
            cached_models=json.dumps(cached),
            hidden_models=json.dumps(hidden),
        )

        result = _default_chat_for(monkeypatch, endpoint, user, is_admin=is_admin)

        assert result["model"] == expected, (user, cached)


def test_visible_models_drops_hidden_entries():
    from routes.model_routes import _visible_models

    assert _visible_models('["hidden-model", "visible-model"]', '["hidden-model"]') == ["visible-model"]
    assert _visible_models('["hidden-a", "hidden-b"]', '["hidden-a", "hidden-b"]') == []
    assert _visible_models('["model-a", "model-b"]', None) == ["model-a", "model-b"]
    assert _visible_models([], None) == []
