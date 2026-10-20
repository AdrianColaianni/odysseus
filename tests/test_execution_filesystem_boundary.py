"""The filesystem execution boundary: what the namespace binds, and what a
spawn says when there is no namespace to bind it with.

Two separate defects, both on the agent shell/Python path.

**The writable /home bind.** The workspace namespace bound ``/home`` and
``/mnt`` read-write. On the one platform where the namespace engages at all,
a command inside it reached outside the workspace and wrote to the user's home
directory. That was measured on a Linux host with working bubblewrap by
running this repo's own argv, so it is not a source read. Binding the user's
whole home directory into a workspace-confinement namespace gives back most of
what the namespace was for.

**The silent downgrade.** ``namespaced or _replace_workspace_alias(...)`` chose
between a mount namespace and a regex, with nothing in the tool result saying
which one ran. The fallback is a naming convenience — it rewrites the literal
token ``/workspace`` in the command string — so a command that never mentions
``/workspace`` is untouched by it and runs on the host unrestricted. That is
every agent shell command on macOS, which is a platform this project is
maintained and run on.

The argv tests assert the argv rather than running it: bubblewrap does not
exist on macOS, and it does not work in Docker either without
``--privileged`` (default and ``seccomp=unconfined`` both give
"Creating new namespace failed", ``--cap-add=SYS_ADMIN`` gives
"pivot_root: Operation not permitted"). An argv assertion is what can honestly
be checked on this host; the execution evidence for the defect itself came from
a Linux host.
"""
import os

import pytest

from src import containment
from src.agent_tools import subprocess_tools
from src.constants import WORKSPACE_MOUNT


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "artifact.txt").write_text("x", encoding="utf-8")
    return str(tmp_path)


def _argv(workspace):
    """The namespace argv, with bubblewrap forced present so it is asserted on every platform."""
    import shutil as _shutil

    original = _shutil.which
    try:
        _shutil.which = lambda name, *a, **kw: (
            "/usr/bin/bwrap" if name == "bwrap" else original(name, *a, **kw)
        )
        return containment._bwrap_prefix(containment.agent_spec(workspace, {}, 5))
    finally:
        _shutil.which = original


def _bind_mode(argv, dest):
    """The bind flag immediately preceding ``src dest`` in the argv, or None."""
    for index in range(len(argv) - 2):
        if argv[index + 2] == dest and argv[index].startswith("--"):
            return argv[index]
    return None


@pytest.mark.skipif(os.name == "nt", reason="bwrap argv is POSIX-only")
def test_the_workspace_is_the_writable_bind(workspace):
    argv = _argv(workspace)
    assert _bind_mode(argv, WORKSPACE_MOUNT) == "--bind"
    assert argv[argv.index("--bind")] == "--bind"


@pytest.mark.skipif(os.name == "nt", reason="bwrap argv is POSIX-only")
def test_the_workspace_stays_writable_at_its_real_host_path_too(workspace):
    """A command can carry the absolute host path, not only /workspace.

    BashTool's /tmp redirect rewrites `/tmp/` to `<agent_cwd()>/.tmp/` before
    the namespace is built, so the command bwrap receives already names the real
    path. Those writes used to land because the workspace happened to sit under
    the writable `/home` bind. With /home read-only they need the workspace's
    own bind, or making /home read-only silently breaks every command that uses
    a real host path.
    """
    real = os.path.realpath(workspace)
    argv = _argv(workspace)
    assert _bind_mode(argv, real) == "--bind", (
        f"expected a writable bind of {real}; argv was {argv}"
    )


@pytest.mark.skipif(os.name == "nt", reason="bwrap argv is POSIX-only")
def test_reserved_destinations_are_never_bound_over(workspace, monkeypatch):
    """Overlaying the private root, tmpfs or the workspace mount with a host
    directory undoes the namespace from inside the argv that builds it."""
    for reserved in ("/", "/tmp", WORKSPACE_MOUNT, "/proc", "/etc", "/usr"):
        assert reserved in subprocess_tools._NAMESPACE_RESERVED_DESTS


@pytest.mark.skipif(os.name == "nt", reason="bwrap argv is POSIX-only")
def test_a_workspace_at_a_reserved_destination_gets_no_extra_bind(monkeypatch):
    """`/tmp` as the workspace must not produce `--bind /tmp /tmp` after the
    argv has already put a private tmpfs there."""
    monkeypatch.setattr(os.path, "realpath", lambda path: "/tmp")
    argv = _argv("/tmp")
    # `--tmpfs /tmp` takes a destination only, so it is a two-arg pair.
    pairs = list(zip(argv, argv[1:]))
    assert ("--tmpfs", "/tmp") in pairs
    assert _bind_mode(argv, "/tmp") is None, (
        f"a host bind of /tmp would undo the private tmpfs; argv was {argv}"
    )


# ── containment.probe: the single answer both tools ask for ─────────────────
def test_probe_answers_without_writing_a_grant_record(workspace, monkeypatch, tmp_path):
    """A grant record whose pid is never filled in and whose release never runs
    is an entry a restart reaper keeps finding, which is why the decision does
    not go through acquire()."""
    store = tmp_path / "grants.json"
    monkeypatch.setattr(containment, "CONTAINMENT_STATE_FILE", str(store), raising=False)
    monkeypatch.setattr(containment, "_store_path", lambda: store)
    probe = containment.probe(
        containment.agent_spec(workspace=workspace, env={}, wall_clock_s=5)
    )
    assert probe.mechanism
    assert not store.exists()
    assert containment.active_grants() == []


def test_probe_and_acquire_agree_on_what_this_host_enforces(workspace, monkeypatch, tmp_path):
    """One mechanism table, one answer. A second opinion about what this host
    can enforce is the thing the probe exists to prevent."""
    store = tmp_path / "grants.json"
    monkeypatch.setattr(containment, "_store_path", lambda: store)
    spec = containment.agent_spec(workspace=workspace, env={}, wall_clock_s=5)
    probe = containment.probe(spec)
    grant = containment.acquire(spec, owner="test")
    assert probe.mechanism == grant.mechanism
    assert probe.enforced == grant.enforced
    assert probe.unenforced_required == grant.unenforced_required
    assert probe.contained == grant.contained


def test_probe_refuses_only_under_enforcing_mode(workspace, monkeypatch):
    spec = containment.agent_spec(workspace=workspace, env={}, wall_clock_s=5)
    monkeypatch.setattr(containment, "CONTAINMENT_MODE", containment.MODE_REPORT_ONLY)
    assert containment.probe(spec).refuses is False
    monkeypatch.setattr(containment, "CONTAINMENT_MODE", containment.MODE_ENFORCING)
    probe = containment.probe(spec)
    # Only meaningful where something required is actually missing; on a host
    # with bubblewrap nothing is.
    assert probe.refuses == bool(probe.unenforced_required)


def test_probe_rejects_a_malformed_spec_in_either_mode(tmp_path):
    missing = tmp_path / "not-a-directory"
    with pytest.raises(ValueError, match="not a directory"):
        containment.probe(
            containment.agent_spec(workspace=str(missing), env={}, wall_clock_s=5)
        )


# ── the isolated /tmp stand-in ──────────────────────────────────────────────
def test_isolated_tmp_is_created_inside_the_workspace(workspace):
    path = subprocess_tools._isolated_tmp_dir(workspace)
    assert os.path.isdir(path)
    assert os.path.realpath(path).startswith(os.path.realpath(workspace))


def test_isolated_tmp_degrades_instead_of_raising_on_an_unwritable_workspace(
    workspace, monkeypatch,
):
    """The source tree is read-only in Docker and a workspace can be mounted
    read-only. A command that merely mentions `/tmp/` must not die with an
    OSError traceback because a scratch directory could not be made."""
    def _refuse(*args, **kwargs):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(os, "makedirs", _refuse)
    path = subprocess_tools._isolated_tmp_dir(workspace)
    assert path == os.path.join(workspace, ".tmp")
