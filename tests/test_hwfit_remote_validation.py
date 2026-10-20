import pytest
from fastapi import HTTPException

from core.platform_compat import _ssh_exec_argv
from routes.hwfit_routes import setup_hwfit_routes
from tests.helpers.routes import route_endpoint


def _endpoint(path: str):
    return route_endpoint(setup_hwfit_routes(), path, "GET")


def test_hwfit_routes_reject_option_shaped_ssh_host_and_port():
    for path, kwargs in (
        ("/api/hwfit/system", {}),
        ("/api/hwfit/models", {"limit": 1}),
        ("/api/hwfit/profiles", {"model": "demo"}),
        ("/api/hwfit/image-models", {}),
    ):
        endpoint = _endpoint(path)
        for host, port in (("-oProxyCommand=sh", "22"), ("alice@gpu-box", "-oProxyCommand=sh")):
            with pytest.raises(HTTPException) as exc:
                endpoint(host=host, ssh_port=port, **kwargs)
            assert exc.value.status_code == 400, (path, host, port)


def test_hwfit_routes_reject_port_without_host():
    endpoint = _endpoint("/api/hwfit/system")

    with pytest.raises(HTTPException) as exc:
        endpoint(host="", ssh_port="2222")

    assert exc.value.status_code == 400


def test_ssh_argv_rejects_option_shaped_remote():
    with pytest.raises(ValueError):
        _ssh_exec_argv("-oProxyCommand=sh", "22", remote_cmd="true")
    with pytest.raises(ValueError):
        _ssh_exec_argv("alice@-oProxyCommand=sh", "22", remote_cmd="true")


def test_detect_system_option_host_never_starts_ssh(monkeypatch):
    from core import platform_compat
    from services.hwfit import hardware

    calls = []

    def _record_subprocess_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("ssh subprocess should not start")

    monkeypatch.setattr(platform_compat.subprocess, "run", _record_subprocess_run)
    hardware._cache_by_host.clear()

    try:
        result = hardware.detect_system(
            host="-oProxyCommand=sh",
            ssh_port="22",
            platform="linux",
            fresh=True,
        )
    finally:
        hardware._cache_by_host.clear()

    assert result == {
        "error": "Cannot connect to -oProxyCommand=sh",
        "host": "-oProxyCommand=sh",
    }
    assert calls == []
