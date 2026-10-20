"""Wave 5A browser lifecycle: ownership, cleanup, recovery and freshness."""

import asyncio
import json
import shutil
import signal
from pathlib import Path

import pytest

from core import platform_compat
from src import browser_lifecycle, process_ownership
from src.agent_tools.web_tools import PrivateBrowserTool


def _fake_proc(root: Path, pid: int, *, ppid: int, pgid: int, sid: int, cmdline: str,
               state: str = "S", starttime: int | None = None) -> None:
    entry = root / str(pid)
    entry.mkdir(parents=True)
    # A full stat line: fields after the comm up to starttime (field 22), which
    # is what process identity is read from.
    tail = " ".join(["0"] * 15 + [str(starttime if starttime is not None else 1000 + pid)])
    (entry / "stat").write_text(f"{pid} (x y) {state} {ppid} {pgid} {sid} {tail}")
    (entry / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode())


@pytest.fixture
def fake_procfs(monkeypatch, tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    boot = proc / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("fake-boot\n")
    monkeypatch.setattr(platform_compat, "PROC_ROOT", proc)
    # Identity reads its own binding of the proc root.
    monkeypatch.setattr(process_ownership, "PROC_ROOT", proc)
    killed: list[tuple[int, int]] = []

    def _kill(pid, sig):
        entry = proc / str(pid)
        if not entry.exists():
            raise ProcessLookupError(pid)
        killed.append((pid, sig))
        shutil.rmtree(entry)

    monkeypatch.setattr(browser_lifecycle.os, "kill", _kill)
    return proc, killed


def _browser_tree(proc: Path, profile: Path, *, daemon: int = 500, extra_sid: int = 900) -> None:
    _fake_proc(proc, daemon, ppid=1, pgid=daemon, sid=daemon, cmdline="/x/agent-browser-linux-x64")
    _fake_proc(proc, daemon + 1, ppid=daemon, pgid=daemon + 1, sid=daemon,
               cmdline=f"chrome --no-sandbox --user-data-dir={profile}")
    _fake_proc(proc, daemon + 2, ppid=daemon + 1, pgid=daemon + 1, sid=daemon, cmdline="chrome --type=renderer")
    _fake_proc(proc, extra_sid, ppid=1, pgid=extra_sid, sid=extra_sid, cmdline="chrome --type=renderer")


def test_runtime_root_follows_agent_browser_resolution(monkeypatch, tmp_path) -> None:
    for name in ("AGENT_BROWSER_SOCKET_DIR", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert browser_lifecycle.runtime_root({"HOME": str(tmp_path)}) == tmp_path / ".agent-browser"
    assert browser_lifecycle.runtime_root(
        {"HOME": str(tmp_path), "XDG_RUNTIME_DIR": "/run/x"}
    ) == Path("/run/x/agent-browser")
    assert browser_lifecycle.runtime_root(
        {"XDG_RUNTIME_DIR": "/run/x", "AGENT_BROWSER_SOCKET_DIR": "/s"}
    ) == Path("/s")


def test_live_daemon_owns_its_whole_session_and_nothing_else(fake_procfs, tmp_path) -> None:
    proc, _ = fake_procfs
    _browser_tree(proc, tmp_path / "agent-browser-chrome-a")

    assert browser_lifecycle.browser_tree(500) == [500, 501, 502]


def test_orphaned_tree_is_claimed_only_through_its_browser_profile(fake_procfs, tmp_path) -> None:
    proc, _ = fake_procfs
    _browser_tree(proc, tmp_path / "agent-browser-chrome-a")
    shutil.rmtree(proc / "500")
    # A reused pid's session without an agent-browser profile is not ours.
    _fake_proc(proc, 700, ppid=1, pgid=700, sid=500, cmdline="bash")

    assert browser_lifecycle.browser_tree(500) == [501, 502]


def test_forced_cleanup_kills_tree_and_removes_owned_resources(fake_procfs, tmp_path) -> None:
    proc, killed = fake_procfs
    root = tmp_path / "rt"
    root.mkdir()
    profile = tmp_path / "agent-browser-chrome-a"
    profile.mkdir()
    (profile / "Default").mkdir()
    for suffix in browser_lifecycle.RUNTIME_SUFFIXES:
        (root / f"ody-k{suffix}").write_text("500")
    (root / "ody-other.pid").write_text("900")
    _browser_tree(proc, profile)

    receipt = browser_lifecycle.force_cleanup(root, "ody-k")

    assert [pid for pid, _ in killed] == [501, 502, 500]
    assert all(sig == signal.SIGKILL for _, sig in killed)
    assert receipt.verified and receipt.killed == 3 and receipt.removed_profiles == 1
    assert not profile.exists()
    assert sorted(p.name for p in root.iterdir()) == ["ody-other.pid"]
    assert (proc / "900").exists()


def test_member_recycled_between_membership_and_identity_is_never_signalled(
    fake_procfs, tmp_path, monkeypatch,
) -> None:
    """Membership sees the old renderer; its pid is reused before any capture or signal.

    The replacement is an unrelated process occupying the same pid slot. Its
    identity must never be the one teardown verifies, so it is never hit.
    """
    proc, killed = fake_procfs
    _browser_tree(proc, tmp_path / "agent-browser-chrome-a")
    lifecycle = browser_lifecycle.process_lifecycle
    recycled = []

    def recycle_once():
        if not recycled:
            recycled.append(True)
            shutil.rmtree(proc / "502")
            _fake_proc(proc, 502, ppid=1, pgid=502, sid=502, cmdline="sshd", starttime=99999)

    # Whichever comes first after membership is decided — an identity capture
    # or the signalling sweep — the old renderer is gone and its pid reissued.
    real_capture = lifecycle.ProcessIdentity.capture
    real_terminate = lifecycle.terminate_identities

    def capture(pid, **kwargs):
        recycle_once()
        return real_capture(pid, **kwargs)

    def terminate(identities, **kwargs):
        identities = list(identities)
        recycle_once()
        return real_terminate(identities, **kwargs)

    monkeypatch.setattr(lifecycle.ProcessIdentity, "capture", staticmethod(capture))
    monkeypatch.setattr(lifecycle, "terminate_identities", terminate)

    killed_pids, survivors, _ = browser_lifecycle.kill_browser_tree(500, settle_s=0.1)

    assert recycled, "the race was never staged"
    assert 502 not in [pid for pid, _ in killed], "the replacement process was signalled"
    assert (proc / "502").exists()
    assert killed_pids == [501, 500] and survivors == []


def test_member_without_identity_is_a_survivor_and_keeps_its_profile(fake_procfs, tmp_path) -> None:
    proc, killed = fake_procfs
    root = tmp_path / "rt"
    root.mkdir()
    (root / "ody-k.pid").write_text("500")
    profile = tmp_path / "agent-browser-chrome-a"
    profile.mkdir()
    _browser_tree(proc, profile)
    # The renderer's stat is unreadable as identity (no start time): this host
    # cannot say which process holds the pid, so it must not be signalled.
    (proc / "502" / "stat").write_text("502 (x y) S 501 501 500")

    receipt = browser_lifecycle.force_cleanup(root, "ody-k")

    assert 502 not in [pid for pid, _ in killed]
    assert receipt.survivors == [502] and not receipt.verified
    assert profile.exists() and (root / "ody-k.pid").exists()


def test_forced_cleanup_without_procfs_never_kills_unverified_processes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(platform_compat, "PROC_ROOT", tmp_path / "missing")
    monkeypatch.setattr(browser_lifecycle.os, "kill", lambda *a: pytest.fail("killed"))
    root = tmp_path / "rt"
    root.mkdir()
    (root / "ody-k.pid").write_text("4242")

    live = browser_lifecycle.force_cleanup(root, "ody-k", pid_alive=lambda pid: True)
    assert not live.verified and (root / "ody-k.pid").exists()

    dead = browser_lifecycle.force_cleanup(root, "ody-k", pid_alive=lambda pid: False)
    assert dead.verified and not (root / "ody-k.pid").exists()


def test_research_reader_passes_its_timeout_to_the_browser(monkeypatch) -> None:
    from src.research_navigator import ResearchNavigator

    seen = {}

    async def _execute(self, content, ctx):
        seen.update(json.loads(content))
        return {"output": "", "exit_code": 1}

    monkeypatch.setattr(PrivateBrowserTool, "execute", _execute)
    navigator = ResearchNavigator.__new__(ResearchNavigator)
    navigator._progress = None
    navigator.session_id = "r"
    asyncio.run(navigator.browser_read("https://example.com", timeout=12))

    assert seen["timeout_ms"] == 12000


def test_browser_mcp_call_is_bounded_and_never_replayed(monkeypatch) -> None:
    from src.mcp_manager import McpManager

    manager = McpManager()
    calls = []

    class _Session:
        async def call_tool(self, name, arguments):
            calls.append(name)
            await asyncio.sleep(3600)

    manager._sessions["builtin_browser"] = _Session()
    monkeypatch.setenv("ODYSSEUS_BROWSER_MCP_CALL_TIMEOUT_S", "0.05")

    result = asyncio.run(manager.call_tool(
        "mcp__builtin_browser__browser_navigate", {"url": "https://example.com"}
    ))

    assert result["exit_code"] == 1
    assert "timed out after 0.05s and was not retried" in result["error"]
    assert calls == ["browser_navigate"]
