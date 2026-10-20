from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]


def _optional_requirement(name):
    lines = (ROOT / "requirements-optional.txt").read_text(encoding="utf-8").splitlines()
    return Requirement(next(line for line in lines if line.startswith(name)))


def test_kokoro_feature_markers_match_supported_python_range():
    for python_version, selected in (("3.12", True), ("3.13", False)):
        for name in ("kokoro", "soundfile"):
            requirement = _optional_requirement(name)
            assert requirement.marker is not None
            assert requirement.marker.evaluate({"python_version": python_version}) is selected
