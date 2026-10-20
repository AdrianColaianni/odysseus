"""Run an ES-module snippet under Node from the repo root and read the JSON it prints.

Use for tests that import a `static/js` module and assert on what a function
returns. Not for browser tests (those launch Playwright) or scripts that need
stdin, extra Node flags, or a nonzero exit code: keep those local.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_node_module(script: str, *, cwd: Path = ROOT, timeout: int = 30):
    """Run `script` as an ES module and return its last stdout line parsed as JSON.

    Skips the calling test when `node` is not on PATH. Relative imports resolve
    against `cwd`, the repo root by default.
    """
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    result = subprocess.run(
        ["node", "--input-type=module", "-e", textwrap.dedent(script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"node printed nothing; stderr: {result.stderr}"
    return json.loads(lines[-1])
