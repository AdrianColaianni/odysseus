"""CPU architecture normalization for HW Fit hardware detection."""

import pytest

from services.hwfit import hardware


@pytest.fixture(autouse=True)
def _clear_hwfit_cache(monkeypatch):
    hardware._cache_by_host.clear()
    monkeypatch.setattr(hardware, "_is_containerized", lambda: False)
    yield
    hardware._cache_by_host.clear()


def _stub_common_probe(monkeypatch, machine):
    monkeypatch.setattr(hardware.platform, "machine", lambda: machine)
    monkeypatch.setattr(hardware, "_get_ram_gb", lambda remote=None: 64.0)
    monkeypatch.setattr(hardware, "_get_available_ram_gb", lambda remote=None: 48.0)
    monkeypatch.setattr(hardware, "_get_cpu_count", lambda remote=None: 16)
    monkeypatch.setattr(hardware, "_get_cpu_name", lambda remote=None: "Test CPU")
    monkeypatch.setattr(hardware, "_detect_apple_silicon", lambda remote=None: None)
    monkeypatch.setattr(hardware, "_detect_amd", lambda remote=None: None)


def test_detect_system_reports_cpu_arch_for_gpu_backends(monkeypatch):
    """GPU-backed systems still need CPU architecture for cpu_only estimates."""
    _stub_common_probe(monkeypatch, "aarch64")
    monkeypatch.setattr(hardware, "_detect_nvidia", lambda remote=None: {
        "gpu_name": "NVIDIA GB10",
        "gpu_vram_gb": 64.0,
        "gpu_count": 1,
        "gpus": [],
        "gpu_groups": [],
        "homogeneous": True,
        "backend": "cuda",
    })

    system = hardware.detect_system(fresh=True)

    assert system["backend"] == "cuda"
    assert system["cpu_arch"] == "arm64"


def test_detect_system_keeps_32_bit_arm_on_conservative_cpu_backend(monkeypatch):
    """Plain arm/armv7 is not the same as the ARM64-class cpu_arm fallback."""
    _stub_common_probe(monkeypatch, "armv7l")
    monkeypatch.setattr(hardware, "_detect_nvidia", lambda remote=None: None)

    system = hardware.detect_system(fresh=True)

    assert system["cpu_arch"] == "arm"
    assert system["backend"] == "cpu_x86"
