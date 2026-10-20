"""Windows execution contract for the agent Bash tool."""

import asyncio

import pytest

from src.agent_tools import subprocess_tools
from src import containment
from tests.containment_helpers import capture_owned_spawn
from tests.process_resource_helpers import authorized_handler


@pytest.mark.asyncio
async def test_windows_bash_tool_passes_ctx_env_through_to_the_child(monkeypatch, tmp_path):
    captured = capture_owned_spawn(monkeypatch, tmp_path)
    env = {"PATH": r"C:\Odysseus\venv\Scripts", "VIRTUAL_ENV": r"C:\Odysseus\venv"}

    monkeypatch.setattr(containment, "IS_WINDOWS", True)
    monkeypatch.setattr(containment, "find_bash", lambda: r"C:\Program Files\Git\bin\bash.exe")
    monkeypatch.setattr("src.tool_execution.agent_cwd", lambda: str(tmp_path))

    result = await authorized_handler(subprocess_tools.BashTool().execute, tmp_path)(
        "pwd",
        {"subproc_env": env, "session_id": "chat-1"},
    )

    assert result["output"] == "ok"
    assert result["exit_code"] == 0
    assert "containment" in result
    assert captured["kwargs"]["env"] == env
    assert captured["kwargs"]["stdout"] == asyncio.subprocess.PIPE
    assert captured["kwargs"]["stderr"] == asyncio.subprocess.PIPE


@pytest.mark.asyncio
async def test_bash_tool_returns_install_hint_when_git_bash_is_missing(monkeypatch, tmp_path):
    capture_owned_spawn(monkeypatch, tmp_path)
    monkeypatch.setattr(containment, "IS_WINDOWS", True)
    monkeypatch.setattr(containment, "find_bash", lambda: None)
    monkeypatch.setattr("src.tool_execution.agent_cwd", lambda: str(tmp_path))

    result = await authorized_handler(subprocess_tools.BashTool().execute, tmp_path)(
        "pwd",
        {"subproc_env": {}, "session_id": None},
    )

    assert result["exit_code"] == 1
    assert "install Git for Windows" in result["error"]


@pytest.mark.asyncio
async def test_windows_bash_does_not_use_a_stray_tmux_executable(monkeypatch, tmp_path):
    captured = capture_owned_spawn(monkeypatch, tmp_path)
    workspace = str(tmp_path)

    monkeypatch.setattr(containment, "IS_WINDOWS", True)
    monkeypatch.setattr(containment, "find_bash", lambda: r"C:\Program Files\Git\bin\bash.exe")
    monkeypatch.setattr(
        subprocess_tools.shutil,
        "which",
        lambda name: r"C:\msys64\usr\bin\tmux.exe",
    )
    monkeypatch.setattr("src.tool_execution.agent_cwd", lambda: workspace)

    async def fail_tmux(*_args, **_kwargs):
        pytest.fail("native Windows must not enter the POSIX tmux path")

    monkeypatch.setattr(subprocess_tools.asyncio, "create_subprocess_shell", fail_tmux)

    result = await authorized_handler(subprocess_tools.BashTool().execute, workspace)(
        "pwd",
        {"subproc_env": {}, "session_id": "chat-1"},
    )

    assert result["output"] == "ok"
    assert result["exit_code"] == 0
    # Every bash result now carries the execution boundary it actually got.
    # Asserting dict equality here would make that field impossible to add
    # without touching a test about tmux, so the shape is asserted instead.
    assert result["containment"]["network"] == "inherit"
    assert captured["command"] == "pwd"
    assert captured["kwargs"]["cwd"] == workspace
