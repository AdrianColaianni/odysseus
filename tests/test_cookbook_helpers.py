import json
import os
import subprocess
import sys

import pytest
from fastapi import HTTPException

from routes.cookbook_helpers import (
    _cached_model_scan_script,
    _append_llama_cpp_linux_accel_build_lines,
    _append_pip_install_runner_lines,
    _append_serve_exit_code_lines,
    _append_serve_preflight_exit_lines,
    _llama_cpp_rebuild_cmd,
    _append_vllm_linux_preflight_lines,
    _local_tooling_path_export,
    _local_windows_bash_env_prefix,
    _pip_install_attempt,
    _pip_install_fallback_chain,
    _ollama_bind_from_cmd,
    _safe_env_prefix,
    _user_shell_path_bootstrap,
    _venv_safe_local_pip_install_cmd,
    _normalize_llama_cpp_python_cache_types,
    _validate_gpus,
    _validate_local_dir,
    _validate_repo_id,
    _validate_serve_cmd,
    _validate_serve_model_id,
    _shell_path,
    run_ssh_command_async,
)


def test_safe_env_prefix_accepts_quoted_venv_path():
    assert (
        _safe_env_prefix("source '~/vllm-env/bin/activate'")
        == '[ -f "$HOME/vllm-env/bin/activate" ] && source "$HOME/vllm-env/bin/activate" || true'
    )


@pytest.mark.asyncio
async def test_run_ssh_command_executes_with_stdin_and_returns_output(monkeypatch):
    captured = {}

    class _Proc:
        returncode = 0

        async def communicate(self, input=None):
            captured["input"] = input
            return b"stdout", b"stderr"

    async def _fake_exec(*args, **kwargs):
        captured["args"] = list(args)
        captured["stdin"] = kwargs.get("stdin")
        captured["stdout"] = kwargs.get("stdout")
        captured["stderr"] = kwargs.get("stderr")
        return _Proc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

    rc, out, err = await run_ssh_command_async(
        "alice@gpu-box",
        "2222",
        "python -",
        timeout=5,
        connect_timeout=4,
        strict_host_key_checking=False,
        stdin_data=b"python -m pip install vllm",
    )

    assert rc == 0
    assert out == b"stdout"
    assert err == b"stderr"
    assert captured["args"] == [
        "ssh",
        "-o",
        "ConnectTimeout=4",
        "-o",
        "StrictHostKeyChecking=no",
        "-p",
        "2222",
        "alice@gpu-box",
        "python -",
    ]
    assert captured["stdin"] is not None
    assert captured["stdout"] is not None
    assert captured["stderr"] is not None
    assert captured["input"] == b"python -m pip install vllm"


def test_safe_env_prefix_leaves_compound_conda_prefix_unchanged():
    prefix = 'eval "$(conda shell.bash hook)" && conda activate qwen35'
    assert _safe_env_prefix(prefix) == prefix


def test_safe_env_prefix_rejects_freeform_shell():
    with pytest.raises(HTTPException):
        _safe_env_prefix("echo ok; curl https://example.invalid")


def test_safe_env_prefix_accepts_powershell_activation_path():
    assert (
        _safe_env_prefix("& 'C:\\Users\\me\\venv\\Scripts\\Activate.ps1'")
        == "& 'C:\\Users\\me\\venv\\Scripts\\Activate.ps1'"
    )


def test_local_windows_bash_env_prefix_converts_powershell_venv_activation():
    for prefix, expected in [
        ("& 'C:\\Users\\me\\venv\\Scripts\\Activate.ps1'", "source /c/Users/me/venv/Scripts/activate"),
        (r"& C:\Users\me\venv\Scripts\Activate.ps1", "source /c/Users/me/venv/Scripts/activate"),
        (r"& C:\Users\me\My Envs\venv\Scripts\Activate.ps1", "source '/c/Users/me/My Envs/venv/Scripts/activate'"),
        (r"& D:/Envs/venv/Scripts/Activate.ps1", "source /d/Envs/venv/Scripts/activate"),
    ]:
        converted = _local_windows_bash_env_prefix(prefix)
        assert converted == expected, prefix
        assert _safe_env_prefix(converted).startswith('[ -f "')


def test_local_windows_bash_env_prefix_leaves_other_prefixes_unchanged():
    for prefix in [
        None,
        "",
        "source /home/me/venv/bin/activate",
        'eval "$(conda shell.bash hook)" && conda activate qwen35',
        r"& \\server\share\venv\Scripts\Activate.ps1",
        "\t" * 100_000,
    ]:
        assert _local_windows_bash_env_prefix(prefix) == prefix


def test_validate_local_dir_accepts_paths_with_spaces_and_unicode():
    for path in [
        "/Volumes/T7 2TB/AI Models/llamacpp",
        r"D:\AI Models\llamacpp",
        "D:/AI Models/llamacpp",
        "/Volumes/Модели/llamacpp",
        "/Volumes/モデル/llm",
    ]:
        assert _validate_local_dir(path) == path
        assert _validate_local_dir(f'"{path}"') == path
    assert _shell_path("/Volumes/T7 2TB/AI Models/llamacpp/Qwen3-8B") == '"/Volumes/T7 2TB/AI Models/llamacpp/Qwen3-8B"'
    assert _shell_path(r"D:\AI Models\llamacpp\Qwen3-8B") == '"D:\\AI Models\\llamacpp\\Qwen3-8B"'


def test_validate_local_dir_rejects_shell_metacharacters_and_option_segments():
    # A segment starting with '-' is read as a CLI option by hf even when quoted.
    for path in [
        "/Volumes/T7 2TB/AI Models; touch /tmp/pwned",
        "/Volumes/T7 2TB/AI Models/$(touch pwned)",
        "/Volumes/T7 2TB/AI Models/`touch pwned`",
        "/Volumes/T7 2TB/AI Models/model\nnext",
        r"D:\AI Models\llamacpp; touch C:\pwned",
        "/Volumes/Модели/a|b",
        r"D:\Модели\llamacpp & calc.exe",
        "/models/-rf",
        "/-oStrictHostKeyChecking=no",
        r"D:\models\-rf",
    ]:
        with pytest.raises(HTTPException):
            _validate_local_dir(path)


def test_validate_gpus_accepts_indexes_only():
    assert _validate_gpus("0,1,2") == "0,1,2"
    with pytest.raises(HTTPException):
        _validate_gpus("0; rm -rf /")


def test_validate_repo_id_stays_strict_for_hf_downloads():
    assert _validate_repo_id("Qwen/Qwen3-8B") == "Qwen/Qwen3-8B"
    with pytest.raises(HTTPException):
        _validate_repo_id("DeepSeek-R1-UD-IQ4_XS")


def test_validate_serve_model_id_accepts_cached_local_model_names():
    assert _validate_serve_model_id("Qwen/Qwen3-8B") == "Qwen/Qwen3-8B"
    assert _validate_serve_model_id("DeepSeek-R1-UD-IQ4_XS") == "DeepSeek-R1-UD-IQ4_XS"
    with pytest.raises(HTTPException):
        _validate_serve_model_id("../escape")


def test_local_tooling_path_export_prepends_interpreter_bin():
    """The cookbook runners must see the venv's bin (where `hf`/`python` live)
    so tmux shells can find them without an activated venv."""
    assert (
        _local_tooling_path_export("/opt/venv/bin/python")
        == 'export PATH="/opt/venv/bin:$PATH"'
    )


def test_local_tooling_path_export_preserves_spaces_and_expands_path():
    line = _local_tooling_path_export("/Users/John Smith/.venv/bin/python3")
    assert line == 'export PATH="/Users/John Smith/.venv/bin:$PATH"'
    assert line.endswith(':$PATH"')  # $PATH stays expandable in double quotes


def _stub_tools(tmp_path, *names):
    """Put logging stand-ins for `names` first on PATH.

    Each stub appends `<name> <args>` to calls.log. Exit codes come from env:
    VENV_RC for the `-c` venv probe, BREAK_RC, USER_RC and BASE_RC for the
    three install attempts. `--help` lists --break-system-packages only when
    HELP_HAS_BREAK is set.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    for name in names:
        stub = bin_dir / name
        stub.write_text(
            "#!/bin/bash\n"
            f'echo "{name} $*" >> "{log}"\n'
            'case "$*" in\n'
            '  "-c "*) exit "${VENV_RC:-1}" ;;\n'
            '  *--help*) [ -n "$HELP_HAS_BREAK" ] && echo "  --break-system-packages"; exit 0 ;;\n'
            '  *--break-system-packages*) exit "${BREAK_RC:-0}" ;;\n'
            '  *--user*) exit "${USER_RC:-0}" ;;\n'
            '  *) echo "boom from base install" >&2; exit "${BASE_RC:-0}" ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    return bin_dir, log


def _run_bash(script, bin_dir, **env):
    full_env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", **env}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=full_env, timeout=15)


def test_pip_install_attempt_exits_with_pip_status_and_shows_its_output(tmp_path):
    bin_dir, _ = _stub_tools(tmp_path, "python3")
    snippet = _pip_install_attempt("python3 -m pip install -q pkg")

    failed = _run_bash(snippet, bin_dir, BASE_RC="3")
    assert failed.returncode == 3
    assert "boom from base install" in failed.stdout
    assert _run_bash(snippet, bin_dir, BASE_RC="0").returncode == 0


def test_pip_install_fallback_chain_propagates_failure_in_venv(tmp_path):
    """Inside a venv a failed base install must fail the chain, not try --user (#903)."""
    bin_dir, log = _stub_tools(tmp_path, "python3")

    result = _run_bash(_pip_install_fallback_chain("pkg"), bin_dir, BASE_RC="1", VENV_RC="0")

    assert result.returncode != 0
    assert "--user" not in log.read_text()


def test_pip_install_fallback_chain_outside_venv_tries_user_then_guarded_break_system(tmp_path):
    bin_dir, log = _stub_tools(tmp_path, "python3")
    chain = _pip_install_fallback_chain("pkg", upgrade=True)

    assert _run_bash(chain, bin_dir, BASE_RC="1", VENV_RC="1", USER_RC="0").returncode == 0
    assert "python3 -m pip install --user -q -U pkg" in log.read_text()
    assert "--break-system-packages -q" not in log.read_text()

    log.unlink()
    result = _run_bash(chain, bin_dir, BASE_RC="1", VENV_RC="1", USER_RC="1", BREAK_RC="0", HELP_HAS_BREAK="1")
    assert result.returncode == 0
    assert "python3 -m pip install --user --break-system-packages -q -U pkg" in log.read_text()

    log.unlink()
    result = _run_bash(chain, bin_dir, BASE_RC="1", VENV_RC="1", USER_RC="1")
    assert result.returncode != 0
    assert "--break-system-packages -q" not in log.read_text()


def test_pip_install_fallback_chain_probes_venv_with_the_pips_own_python(tmp_path):
    bin_dir, log = _stub_tools(tmp_path, "pip", "python", "python3")

    _run_bash(_pip_install_fallback_chain("pkg", python_cmd="pip"), bin_dir, BASE_RC="1", VENV_RC="0")
    calls = log.read_text().splitlines()
    assert calls[0] == "pip install -q pkg"
    assert calls[1].startswith("python -c ")

    log.unlink()
    _run_bash(_pip_install_fallback_chain("pkg", python_cmd="python"), bin_dir, BASE_RC="0")
    assert log.read_text().splitlines() == ["python -m pip install -q pkg"]


def test_pip_install_fallback_chain_quotes_extras_spec():
    """An extras spec like ``llama-cpp-python[server]`` must be shell-quoted so
    bash does not treat the brackets as a glob, and the ``[server]`` extra
    (which pulls in starlette_context for ``python -m llama_cpp.server``) is
    actually installed instead of a bare ``llama-cpp-python`` (issue #730)."""
    chain = _pip_install_fallback_chain("llama-cpp-python[server]", python_cmd="pip")
    # Quoted in the plain, --user, and guarded --break-system-packages attempts.
    assert chain.count("'llama-cpp-python[server]'") == 3
    # llama-cpp installs must prefer prebuilt wheels to avoid fragile source builds.
    assert "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" in chain
    # Never the unquoted form (bracket-glob risk).
    assert "install -q llama-cpp-python[server]" not in chain
    # A plain package name is still passed through unquoted (no regression).
    plain = _pip_install_fallback_chain("hf_transfer", python_cmd="pip")
    assert "install -q hf_transfer" in plain


def test_serve_runner_installs_llama_cpp_server_extra():
    """The llama.cpp serve auto-install must request the ``[server]`` extra in
    every path (issue #730): a bare ``llama-cpp-python`` passes the
    ``import llama_cpp`` guard, so ``python -m llama_cpp.server`` then crashes
    with ``ModuleNotFoundError: No module named 'starlette_context'`` and the
    extra is never reinstalled."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "routes" / "cookbook_routes.py").read_text(encoding="utf-8")
    # No serve path may install a bare (extra-less) llama-cpp-python.
    assert "pip install llama-cpp-python " not in src
    assert "_pip_install_fallback_chain('llama-cpp-python'" not in src
    # The [server] extra is requested in the build/fallback paths.
    assert "'llama-cpp-python[server]'" in src
    assert "_pip_install_fallback_chain('llama-cpp-python[server]'" in src


def test_vllm_preflight_reports_cli_or_marks_it_missing(tmp_path):
    lines = []
    _append_vllm_linux_preflight_lines(lines)
    script = "\n".join(lines) + '\necho "EXIT=$ODYSSEUS_PREFLIGHT_EXIT"'
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = {"HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin"}

    missing = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=10)
    assert "EXIT=127" in missing.stdout

    vllm = bin_dir / "vllm"
    vllm.write_text("#!/bin/sh\necho 0.9.1\n", encoding="utf-8")
    vllm.chmod(0o755)
    found = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=10)
    assert "EXIT=\n" in found.stdout
    assert str(vllm) in found.stdout
    assert "0.9.1" in found.stdout


def test_venv_safe_local_pip_install_strips_user_flags_only_for_local_venv():
    cmd = 'python3 -m pip install -U --user --break-system-packages "vllm"'

    cleaned = _venv_safe_local_pip_install_cmd(cmd, local=True, in_venv=True)

    assert cleaned == "python3 -m pip install -U vllm"
    assert _venv_safe_local_pip_install_cmd(cmd, local=False, in_venv=True) == cmd
    assert _venv_safe_local_pip_install_cmd(cmd, local=True, in_venv=False) == cmd


def test_pip_install_runner_drops_break_system_packages_for_old_pip(tmp_path):
    bin_dir, log = _stub_tools(tmp_path, "python3")
    lines = []
    _append_pip_install_runner_lines(
        lines,
        'python3 -m pip install --no-cache-dir --user --break-system-packages "llama-cpp-python[server]"',
    )
    script = "\n".join(lines)

    _run_bash(script, bin_dir)
    assert log.read_text().splitlines()[-1] == "python3 -m pip install --no-cache-dir --user llama-cpp-python[server]"

    log.unlink()
    _run_bash(script, bin_dir, HELP_HAS_BREAK="1")
    assert log.read_text().splitlines()[-1] == (
        "python3 -m pip install --no-cache-dir --user --break-system-packages llama-cpp-python[server]"
    )


def test_pip_install_runner_leaves_plain_commands_unchanged():
    lines = []
    _append_pip_install_runner_lines(lines, "python3 -m pip install --no-cache-dir vllm")

    assert lines == ["python3 -m pip install --no-cache-dir vllm"]


def test_local_tooling_path_export_converts_windows_paths_for_bash():
    line = _local_tooling_path_export(r"C:\Users\Jane Dev\.venv\Scripts\python.exe")
    assert line == 'export PATH="/c/Users/Jane Dev/.venv/Scripts:$PATH"'
    assert "C:" not in line


def test_user_shell_path_bootstrap_shims_windowsapps_python3_to_python(tmp_path):
    alias_dir = tmp_path / "WindowsApps"
    alias_dir.mkdir()
    (alias_dir / "python3").write_text("#!/bin/sh\necho store-alias\n", encoding="utf-8")
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    (venv_dir / "python").write_text("#!/bin/sh\necho venv-python\n", encoding="utf-8")
    for stub in [alias_dir / "python3", venv_dir / "python"]:
        stub.chmod(0o755)
    script = "\n".join(_user_shell_path_bootstrap()) + "\npython3"

    result = subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True, text=True, timeout=10,
        env={"PATH": f"{alias_dir}:{venv_dir}", "SHELL": ""},
    )

    assert result.stdout.strip() == "venv-python"


def _run_runner(lines, tmp_path):
    shell = tmp_path / "shell"
    shell.write_text("#!/bin/sh\necho shell-open\n", encoding="utf-8")
    shell.chmod(0o755)
    # The runner restores stdout/stderr from fds 3 and 4, saved before its tee.
    script = "exec 3>&1 4>&2\n" + "\n".join(lines)
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=10,
        env={**os.environ, "SHELL": str(shell)},
    )


def test_serve_preflight_failure_keeps_tmux_pane_visible(tmp_path):
    """A bare `exit 127` closes the pane before the status poller reads the error."""
    lines = ["ODYSSEUS_PREFLIGHT_EXIT=127"]
    _append_serve_preflight_exit_lines(lines, keep_shell_open=True)

    result = _run_runner(lines, tmp_path)

    assert "=== Process exited with code 127 ===" in result.stdout
    assert "shell-open" in result.stdout
    assert result.returncode == 0


def test_serve_runner_preserves_command_exit_code(tmp_path):
    lines = ["(exit 7)"]
    _append_serve_exit_code_lines(lines, keep_shell_open=False)

    result = _run_runner(lines, tmp_path)

    assert result.returncode == 7
    assert "=== Process exited with code 7 ===" in result.stdout


def test_pip_serve_runner_emits_download_ok_before_exit_marker(tmp_path):
    lines = ["true"]
    _append_serve_exit_code_lines(lines, keep_shell_open=False, is_pip_install=True)

    out = _run_runner(lines, tmp_path).stdout

    assert out.index("DOWNLOAD_OK") < out.index("=== Process exited with code 0 ===")


def test_validate_serve_cmd_accepts_generated_launch_commands():
    for cmd in [
        (
            "CUDA_VISIBLE_DEVICES=0,1 vllm serve nvidia/Qwen3.6-35B-A3B-NVFP4 "
            "--host 0.0.0.0 --port 8000 --tensor-parallel-size 2 "
            "--max-model-len 4096 --dtype auto --kv-cache-dtype fp8"
        ),
        (
            "MODEL_FILE=$(printf %s ${HOME}'/.cache/huggingface/hub/models--Qwen--Qwen3-GGUF/snapshots/model.gguf') "
            '&& { [ -n "$MODEL_FILE" ] && [ -f "$MODEL_FILE" ]; } '
            '|| { echo "ERROR: No GGUF found on this host."; exit 1; } && '
            'GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 CUDA_VISIBLE_DEVICES=0,1 llama-server '
            '--model "$MODEL_FILE" --host 0.0.0.0 --port 8000 -ngl 99 -c 131072 '
            '--n-cpu-moe 0 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on '
            '--fit off --split-mode tensor --tensor-split 50,50 --main-gpu 0 '
            '--parallel 1 --batch-size 2048 --ubatch-size 512 --no-mmap --no-warmup '
            '--spec-type draft-mtp --spec-draft-n-max 3 '
            '|| python3 -m llama_cpp.server --model "$MODEL_FILE" --host 0.0.0.0 --port 8000'
        ),
        (
            "python -m llama_cpp.server --model "
            "\"$(printf %s ${HOME}'/.cache/huggingface/hub/models--unsloth--Qwen3.5-2B-GGUF/snapshots/f6d5376be1edb4d416d56da11e5397a961aca8ae/Qwen3.5-2B-Q4_K_M.gguf')\" "
            "--host 0.0.0.0 --port 8000 --n_gpu_layers 99 --n_ctx 32768 --flash_attn true --type_k q4_0 --type_v q4_0"
        ),
        (
            "CUDA_VISIBLE_DEVICES=0 llama-server --model "
            "\"$(printf %s ${HOME}'/.cache/huggingface/hub/models--unsloth--Qwen3.6-35B-A3B-GGUF/snapshots/abc/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf')\" "
            "--host 0.0.0.0 --port 8000 -ngl 99 -c 20000 "
            "--cache-type-k q4_0 --cache-type-v q4_0 --mmproj "
            "\"$(printf %s ${HOME}'/.cache/huggingface/hub/models--unsloth--Qwen3.6-35B-A3B-GGUF/snapshots/abc/mmproj-BF16.gguf')\" "
            "--image-max-tokens 1024"
        ),
        (
            "HIP_VISIBLE_DEVICES=0 llama-server "
            "--model \"$(printf %s '/app/.cache/huggingface/hub/models--unsloth--gemma-4-E2B-it-GGUF"
            "/snapshots/90f9618340396838ee7ff5b0ba2da27da62953d3/gemma-4-E2B-it-Q4_K_M.gguf')\" "
            "--host 0.0.0.0 --port 8000 -ngl 99 -c 131072 "
            "--flash-attn on --cache-type-k q8_0 --cache-type-v q8_0 "
            "--mmproj \"$(find '/app/.cache/huggingface/hub/models--unsloth--gemma-4-E2B-it-GGUF"
            "/snapshots' -iname 'mmproj*.gguf' 2>/dev/null | sort | head -1)\" "
            "--image-max-tokens 1024"
        ),
    ]:
        assert _validate_serve_cmd(cmd) == cmd


def test_normalize_llama_cpp_python_cache_types_for_stale_client_cmd():
    cmd = (
        "python -m llama_cpp.server --model model.gguf --host 0.0.0.0 --port 8000 "
        "--type_k q4_0 --type_v q4_0"
    )

    assert _normalize_llama_cpp_python_cache_types(cmd).endswith("--type_k 2 --type_v 2")


def test_normalize_llama_cpp_python_cache_types_preserves_native_cache_flags():
    cmd = (
        "llama-server --model model.gguf --cache-type-k q4_0 --cache-type-v q4_0 "
        "|| python3 -m llama_cpp.server --model model.gguf --type_k=q8_0 --type_v='f16'"
    )

    normalized = _normalize_llama_cpp_python_cache_types(cmd)
    assert "--cache-type-k q4_0 --cache-type-v q4_0" in normalized
    assert "--type_k=8" in normalized
    assert "--type_v='1'" in normalized


def test_ollama_serve_defaults_to_loopback_bind():
    assert _ollama_bind_from_cmd("ollama serve") == ("127.0.0.1", "11434")
    assert _ollama_bind_from_cmd("ollama run qwen2.5:0.5b") == ("127.0.0.1", "11434")


def test_ollama_serve_accepts_remote_reachable_default_bind():
    assert (
        _ollama_bind_from_cmd("ollama serve", default_host="0.0.0.0")
        == ("0.0.0.0", "11434")
    )


def test_ollama_serve_preserves_explicit_bind_opt_in():
    assert (
        _ollama_bind_from_cmd("OLLAMA_HOST=0.0.0.0:12345 ollama serve")
        == ("0.0.0.0", "12345")
    )
    assert (
        _ollama_bind_from_cmd("OLLAMA_HOST=[::1]:11435 ollama serve")
        == ("[::1]", "11435")
    )


def test_ollama_serve_rejects_unsafe_bind_values():
    assert (
        _ollama_bind_from_cmd("OLLAMA_HOST='$HOST:11434' ollama serve")
        == ("127.0.0.1", "11434")
    )
    assert (
        _ollama_bind_from_cmd("OLLAMA_HOST=127.0.0.1:99999 ollama serve")
        == ("127.0.0.1", "11434")
    )


def test_llama_cpp_linux_bootstrap_toolchain_precedence():
    runner_lines = []
    _append_llama_cpp_linux_accel_build_lines(runner_lines)
    script = "\n".join(runner_lines)
    hip = script.index("-DGGML_HIP=ON")
    cuda = script.index("-DGGML_CUDA=ON")

    assert script.index("mkdir -p ~/bin") < script.index("cd ~/llama.cpp")
    assert hip < cuda
    # nvcc without a visible libcudart builds for CPU instead of failing CUDA configure.
    assert script.index("_odysseus_has_cudart") < cuda
    assert script.index("cmake -B build -DCMAKE_BUILD_TYPE=Release &&") < script.index(
        "WARNING: no HIP/CUDA/Vulkan toolchain found"
    )
    assert not any(line.endswith("\\\\") for line in runner_lines)


def test_llama_cpp_rebuild_cmd_clears_cached_build_without_fetching(tmp_path):
    from core.platform_compat import find_bash, git_bash_path

    (tmp_path / "llama.cpp" / "build").mkdir(parents=True)
    cmd = _llama_cpp_rebuild_cmd()
    env = {**os.environ, "HOME": git_bash_path(tmp_path)}
    result = subprocess.run(
        [find_bash() or "bash", "-c", cmd],
        capture_output=True, text=True, env=env, timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "bin").is_dir()
    assert not (tmp_path / "llama.cpp" / "build").exists()
    assert "pip install" not in cmd
    assert "git clone" not in cmd
    assert "curl" not in cmd and "wget" not in cmd


def test_cached_model_scan_reports_plain_dir_gguf(tmp_path):
    """Custom download dirs may sit inside the HF hub cache and contain plain
    per-model folders. They must show up in Serve and keep the GGUF signal."""
    plain = tmp_path / "Qwen3.6-27B"
    plain.mkdir()
    (plain / "Qwen3.6-27B-Q4_K_M.gguf").write_bytes(b"gguf")
    (plain / "Qwen3.6-27B-Q5_K_M-00001-of-00003.gguf").write_bytes(b"part1")
    (plain / "Qwen3.6-27B-Q5_K_M-00002-of-00003.gguf").write_bytes(b"part2")
    (plain / "Qwen3.6-27B-Q5_K_M-00003-of-00003.gguf").write_bytes(b"part3")
    (plain / "Qwen3.6-27B-Q6_K_XL.gguf").write_bytes(b"ggufgguf")
    (plain / "mmproj-BF16.gguf").write_bytes(b"projector")

    hf_internal = tmp_path / "models--Qwen--Qwen3.6-27B"
    (hf_internal / "snapshots" / "abc").mkdir(parents=True)
    (hf_internal / "snapshots" / "abc" / "model.safetensors").write_bytes(b"safe")

    scan_py = tmp_path / "scan_cache.py"
    scan_py.write_text(_cached_model_scan_script([str(tmp_path)]), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(scan_py)],
        check=True,
        capture_output=True,
        text=True,
    )

    by_repo = {m["repo_id"]: m for m in json.loads(proc.stdout)}
    assert "models--Qwen--Qwen3.6-27B" not in by_repo
    assert by_repo["Qwen3.6-27B"]["is_local_dir"] is True
    assert by_repo["Qwen3.6-27B"]["is_gguf"] is True
    ggufs = by_repo["Qwen3.6-27B"]["gguf_files"]
    assert [f["rel_path"] for f in ggufs] == [
        "Qwen3.6-27B-Q4_K_M.gguf",
        "Qwen3.6-27B-Q5_K_M-00001-of-00003.gguf",
        "Qwen3.6-27B-Q6_K_XL.gguf",
        "mmproj-BF16.gguf",
    ]
    assert [f["role"] for f in ggufs] == ["model", "model", "model", "projector"]
    assert ggufs[0]["quant"] == "Q4_K_M"
    assert ggufs[1]["quant"] == "Q5_K_M"
    assert ggufs[1]["split"] is True
    assert ggufs[1]["parts"] == 3
    assert ggufs[1]["size_bytes"] == len(b"part1part2part3")
    assert ggufs[2]["quant"] == "Q6_K_XL"
    assert ggufs[3]["quant"] == "BF16"


@pytest.mark.skipif(os.name != "nt", reason="Windows Ollama CLI startup guard")
def test_cached_model_scan_does_not_launch_ollama_cli_on_windows(tmp_path):
    """Official Ollama for Windows can auto-start the tray/server on `ollama list`.
    The read-only cache scanner must not invoke that CLI unless explicitly opted in.
    """
    marker = tmp_path / "ollama-called.txt"
    fake_ollama = tmp_path / "ollama.cmd"
    fake_ollama.write_text(
        "@echo off\r\n"
        f'echo called>"{marker}"\r\n'
        "echo NAME ID SIZE MODIFIED\r\n"
        "echo local-model:latest abc 1 GB now\r\n",
        encoding="utf-8",
    )

    empty_home = tmp_path / "home"
    empty_home.mkdir()
    scan_py = tmp_path / "scan_cache.py"
    scan_py.write_text(_cached_model_scan_script(), encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = str(tmp_path) + os.pathsep + env.get("PATH", "")
    env["HOME"] = str(empty_home)
    env.pop("ODYSSEUS_ALLOW_OLLAMA_CLI_SCAN", None)
    proc = subprocess.run(
        [sys.executable, str(scan_py)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert marker.exists() is False
    assert all(m.get("backend") != "ollama" for m in json.loads(proc.stdout))


def test_cached_model_scan_uses_huggingface_cache_env(tmp_path):
    """Docker recreates can leave the persisted HF cache outside HOME.
    The Serve scanner should honor the cache env path instead of only ~/.cache.
    """
    hf_cache = tmp_path / "app-cache" / "hub"
    model = hf_cache / "models--Qwen--Qwen3.6-35B"
    (model / "blobs").mkdir(parents=True)
    (model / "blobs" / "weights.safetensors").write_bytes(b"weights")
    (model / "snapshots" / "abc").mkdir(parents=True)
    (model / "snapshots" / "abc" / "config.json").write_text("{}", encoding="utf-8")

    empty_home = tmp_path / "home"
    empty_home.mkdir()
    scan_py = tmp_path / "scan_cache_env.py"
    scan_py.write_text(_cached_model_scan_script(), encoding="utf-8")
    env = dict(os.environ)
    env["HOME"] = str(empty_home)
    env["HUGGINGFACE_HUB_CACHE"] = str(hf_cache)
    proc = subprocess.run(
        [sys.executable, str(scan_py)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    by_repo = {m["repo_id"]: m for m in json.loads(proc.stdout)}
    assert by_repo["Qwen/Qwen3.6-35B"]["path"] == str(hf_cache)


# ── #1219 / #1459: keep big dependency wheel builds off the home pip cache ──

def test_pip_install_no_cache_injects_flag():
    from routes.cookbook_helpers import _pip_install_no_cache
    assert _pip_install_no_cache("python -m pip install vllm") == \
        "python -m pip install --no-cache-dir vllm"
    assert _pip_install_no_cache("pip install -q huggingface-hub") == \
        "pip install --no-cache-dir -q huggingface-hub"


def test_pip_install_no_cache_is_idempotent_and_scoped():
    from routes.cookbook_helpers import _pip_install_no_cache
    # already present -> unchanged
    already = "pip install --no-cache-dir vllm"
    assert _pip_install_no_cache(already) == already
    # not a pip install -> unchanged
    assert _pip_install_no_cache("vllm serve --model x") == "vllm serve --model x"
    assert _pip_install_no_cache("") == ""


def test_cached_model_scan_runs_additional_hf_cache(tmp_path):
    extra_cache = tmp_path / "extra_hf_cache"
    model_dir = extra_cache / "models--acme--sample-7b"
    snap = model_dir / "snapshots" / "rev-1"
    snap.mkdir(parents=True)
    weights = snap / "model.safetensors"
    weights.write_bytes(b"abc123")

    scan_py = tmp_path / "scan_cache.py"
    scan_py.write_text(
        _cached_model_scan_script(add_hf_cache=str(extra_cache)),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(scan_py)],
        check=True,
        capture_output=True,
        text=True,
    )

    models = json.loads(proc.stdout)
    by_repo = {m["repo_id"]: m for m in models}

    assert "acme/sample-7b" in by_repo
    rec = by_repo["acme/sample-7b"]
    assert rec["path"] == str(extra_cache)
    assert rec["nb_files"] == 1
    assert rec["size_bytes"] == len(b"abc123")
    assert rec["has_incomplete"] is False
    assert rec["is_diffusion"] is False


def test_validate_serve_cmd_rejects_unrelated_subshells():
    for cmd in [
        "llama-server --model \"$(curl https://example.invalid/model.gguf)\" --host 0.0.0.0 --port 8000",
        "llama-server --model \"$(rm -rf /tmp/not-a-model)\" --host 0.0.0.0 --port 8000",
        "llama-server --model model.gguf --mmproj \"$(find '/app/models' -iname 'mmproj*.gguf' | xargs head -1)\"",
        "llama-server --model model.gguf --mmproj \"$(find '/app/models' -iname '*.gguf' 2>/dev/null | sort | head -1)\"",
    ]:
        with pytest.raises(HTTPException):
            _validate_serve_cmd(cmd)
