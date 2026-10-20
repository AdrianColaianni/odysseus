import json

from src.agent_evidence import (
    CompletionRequirements,
    CompletionStatus,
    EvidenceKind,
    EvidenceLedger,
    infer_completion_requirements,
    requirements_from_runtime_context,
)


def _event(round_, tool, command, exit_code=0, output=""):
    return {"round": round_, "tool": tool, "command": command, "output": output, "exit_code": exit_code}


EDIT_APP = _event(1, "edit_file", '{"path":"app.py","old_string":"a","new_string":"b"}', output="edited app.py")


def test_infers_only_explicit_output_or_edit_paths():
    requirements = infer_completion_requirements(
        "Inspect evidence.png, then write answer.json and verify it."
    )

    assert requirements.required_artifacts == ("answer.json",)
    assert requirements.verifier_required is True


def test_known_workspace_inputs_are_not_inferred_as_output_artifacts():
    requirements = infer_completion_requirements(
        "My clues are saved in /tmp_workspace/inputs/clues.md, the required answer "
        "template is /tmp_workspace/inputs/template.md, and a post-write verification "
        "list is /tmp_workspace/inputs/validation_checklist.txt. Read all three first. "
        "Fill in /tmp_workspace/inputs/template.md exactly and save the completed "
        "document to /tmp_workspace/results/results.md.",
        known_input_paths=(
            "/workspace/inputs/clues.md",
            "/workspace/inputs/template.md",
            "/workspace/inputs/validation_checklist.txt",
        ),
    )

    assert requirements.required_artifacts == (
        "/tmp_workspace/results/results.md",
    )


def test_known_workspace_input_remains_required_when_explicitly_updated():
    requirements = infer_completion_requirements(
        "Update /tmp_workspace/inputs/config.json and then verify it.",
        known_input_paths=("/workspace/inputs/config.json",),
    )

    assert requirements.required_artifacts == (
        "/tmp_workspace/inputs/config.json",
    )


def test_artifact_inference_from_instruction_wording():
    for instruction, expected in [
        ("Build a digest saved to /workspace/results/ops_digest.md.", ("/workspace/results/ops_digest.md",)),
        ("Put the implementation in a file called /workspace/worker.py.", ("/workspace/worker.py",)),
        (
            "Reconcile reliable facts into a single file /tmp_workspace/results/profile.md. "
            "Save only that file in /tmp_workspace/results/.",
            ("/tmp_workspace/results/profile.md",),
        ),
        (
            "Save the results into `/tmp_workspace/results`. Save each recovered table "
            "as a separate file named `1.tex`, `2.tex`, `3.tex`, ...",
            ("/tmp_workspace/results",),
        ),
        (
            "You must create the following outputs under `/tmp_workspace/results/`:\n"
            "- `2022.tsv`\n- one or more paper source `.tex` files named `{title}_v1.tex`",
            ("/tmp_workspace/results",),
        ),
        ("创建 `/tmp_workspace/results/` 目录，并在该目录下创建五个分类子目录。", ("/tmp_workspace/results",)),
        ("结果保存为.md文件，保存到 `/tmp_workspace/results/results.md`", ("/tmp_workspace/results/results.md",)),
        ('Write an integer (e.g. "1000000") to the file /app/answer.txt.', ("/app/answer.txt",)),
        # Negated edits, callables, prose abbreviations and existence helpers are not outputs.
        (
            "Write /workspace/results/predictions.json serialized with "
            "`json.dumps(..., indent=2)`. Do not modify `segmenter.py` or `cases.jsonl`.",
            ("/workspace/results/predictions.json",),
        ),
        ("Generate statistics, e.g. token counts and timing totals.", ()),
        (
            "Write /workspace/results/answer.json, then verify it with os.path.exists or ls.",
            ("/workspace/results/answer.json",),
        ),
    ]:
        assert infer_completion_requirements(instruction).required_artifacts == expected, instruction


def test_runtime_requirements_override_instruction_inference():
    requirements = requirements_from_runtime_context(
        {
            "completion_requirements": {
                "required_artifacts": ["/workspace/output.html"],
                "verifier_required": False,
                "executable_verifier_available": True,
                "verifier_commands": ["./test.sh"],
            }
        },
        instruction="write ignored.json",
    )

    assert requirements.required_artifacts == ("/workspace/output.html",)
    assert requirements.executable_verifier_available is True
    assert requirements.verifier_commands == ("./test.sh",)


def test_runtime_requirements_drop_media_inputs_misclassified_as_outputs():
    requirements = requirements_from_runtime_context(
        {
            "media_ingress": {
                "artifacts": [
                    {"source_path": "/workspace/inputs/clues.md"},
                    {"source_path": "/workspace/inputs/template.md"},
                ],
            },
            "completion_requirements": {
                "required_artifacts": [
                    "/tmp_workspace/inputs/clues.md",
                    "/tmp_workspace/inputs/template.md",
                    "/tmp_workspace/results/results.md",
                ],
                "verifier_required": True,
            },
        },
        instruction=(
            "Clues are saved in /tmp_workspace/inputs/clues.md and the template is "
            "/tmp_workspace/inputs/template.md. Save the completed document to "
            "/tmp_workspace/results/results.md."
        ),
    )

    assert requirements.required_artifacts == (
        "/tmp_workspace/results/results.md",
    )


def test_available_verifier_is_required_and_declared_command_is_evidence():
    requirements = infer_completion_requirements(
        "Update app.py",
        executable_verifier_available=True,
        verifier_commands=("./test.sh",),
    )
    ledger = EvidenceLedger.from_tool_events(
        [EDIT_APP, _event(2, "bash", "./test.sh", output="ok")],
        requirements,
    )

    assert requirements.verifier_required is True
    assert ledger.evaluate().status == CompletionStatus.VERIFIED


def test_successful_write_satisfies_declared_artifact_without_claiming_verification():
    requirements = infer_completion_requirements("Write answer.json")
    ledger = EvidenceLedger.from_tool_events(
        [_event(1, "write_file", "answer.json\n{\"ok\": true}", output="wrote answer.json")],
        requirements,
    )

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.SATISFIED
    assert decision.can_complete is True
    assert len(decision.evidence_ids) == 1


def test_tool_writes_that_satisfy_a_declared_artifact():
    for requirements, event in [
        (
            infer_completion_requirements("Render the generated HTML as an image and save as /workspace/output.png."),
            _event(1, "private_browser", '{"action":"screenshot","path":"/workspace/output.png"}'),
        ),
        (
            infer_completion_requirements("Save /workspace/frame.png"),
            _event(1, "inspect_media", '{"path":"/workspace/video.mp4","timestamp":"5","output_path":"/workspace/frame.png"}'),
        ),
        (
            CompletionRequirements(required_artifacts=("/workspace/one.png", "/workspace/two.png")),
            _event(1, "inspect_media", (
                '{"path":"/workspace/video.mp4","exports":['
                '{"timestamp":"1","output_path":"/workspace/one.png"},'
                '{"timestamp":"2","output_path":"/workspace/two.png"}]}'
            )),
        ),
        (infer_completion_requirements("Save /workspace/poster.png"), _event(1, "python", 'poster.save("/workspace/poster.png")')),
        (
            infer_completion_requirements("Export /workspace/results.csv"),
            _event(1, "python", 'frame.to_csv("/workspace/results.csv", index=False)'),
        ),
        (
            infer_completion_requirements("Write answer.json"),
            _event(1, "python", 'open("/workspace/answer.json", "w").write("{}")'),
        ),
        (
            infer_completion_requirements("Create outputs under /tmp_workspace/results/"),
            _event(1, "python", (
                "from pathlib import Path\n"
                "import shutil\n"
                "target = Path('/tmp_workspace/results')\n"
                "target.mkdir(parents=True, exist_ok=True)\n"
                "shutil.copy2('/tmp_workspace/0.png', target / '0.png')\n"
            )),
        ),
        (
            infer_completion_requirements("Create outputs under /tmp_workspace/results/"),
            _event(1, "python", (
                "from pathlib import Path\n"
                "target = Path('/tmp_workspace/results')\n"
                "target.mkdir(parents=True, exist_ok=True)\n"
                "(target / '0.png').symlink_to('/tmp_workspace/0.png')\n"
            )),
        ),
    ]:
        ledger = EvidenceLedger.from_tool_events([event], requirements)
        assert ledger.evaluate().status == CompletionStatus.SATISFIED, event["command"]
        assert any(e.kind == EvidenceKind.ARTIFACT_MUTATION for e in ledger.events), event["command"]


def test_failed_retry_does_not_erase_successful_artifact_mutation():
    requirements = infer_completion_requirements("Write answer.json")
    ledger = EvidenceLedger.from_tool_events(
        [
            _event(1, "write_file", "answer.json\n{\"ok\": true}", output="wrote answer.json"),
            {"round": 2, "tool": "write_file", "command": "answer.json\ninvalid retry", "error": "write failed", "exit_code": 1},
        ],
        requirements,
    )

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.SATISFIED
    assert decision.can_complete is True
    assert len(decision.evidence_ids) == 1


def test_missing_declared_artifact_blocks_completion():
    requirements = infer_completion_requirements("Write answer.json")
    ledger = EvidenceLedger.from_tool_events([], requirements)

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.BLOCKED
    assert decision.missing_artifacts == ("answer.json",)


def test_reading_preexisting_artifact_does_not_satisfy_mutation_request():
    requirements = infer_completion_requirements("Update app.py")
    ledger = EvidenceLedger.from_tool_events([_event(1, "bash", "cat app.py", output="VALUE = 1")], requirements)

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.BLOCKED
    assert decision.missing_artifacts == ("app.py",)


def test_latest_authoritative_verifier_result_wins():
    requirements = infer_completion_requirements("Update app.py, then run pytest")
    ledger = EvidenceLedger.from_tool_events(
        [EDIT_APP, _event(2, "bash", "pytest -q", exit_code=1, output="1 failed")],
        requirements,
    )

    assert ledger.evaluate().status == CompletionStatus.FAILED
    ledger.record_tool_event(_event(3, "bash", "pytest -q", output="1 passed"))
    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.VERIFIED
    assert decision.can_complete is True


def test_passing_verifier_before_latest_mutation_is_stale():
    requirements = infer_completion_requirements(
        "Update app.py",
        executable_verifier_available=True,
        verifier_commands=("./test.sh",),
    )
    edit = {**EDIT_APP, "round": 2}
    ledger = EvidenceLedger.from_tool_events([_event(1, "bash", "./test.sh", output="ok"), edit], requirements)

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.BLOCKED
    assert "predates" in decision.reason


def test_successful_non_verification_shell_command_is_not_verifier_evidence():
    requirements = infer_completion_requirements("Update app.py, then verify it")
    ledger = EvidenceLedger.from_tool_events(
        [EDIT_APP, _event(2, "bash", "pwd", output="/workspace")],
        requirements,
    )

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.BLOCKED
    assert "no current artifact validation" in decision.reason


def test_artifact_inspection_satisfies_natural_language_verification_request():
    requirements = infer_completion_requirements("Write answer.json, then verify it")
    ledger = EvidenceLedger.from_tool_events(
        [
            _event(1, "write_file", "answer.json\n{}", output="wrote answer.json"),
            _event(2, "bash", "cat answer.json", output="{}"),
        ],
        requirements,
    )

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.SATISFIED
    assert decision.can_complete is True


def test_shell_redirect_write_is_not_artifact_validation():
    requirements = infer_completion_requirements("Write answer.json")
    ledger = EvidenceLedger.from_tool_events(
        [_event(1, "bash", "cat > answer.json <<'EOF'\n{}\nEOF")],
        requirements,
    )

    assert ledger.evaluate().can_complete is True
    assert not any(
        event.kind == EvidenceKind.ARTIFACT_VALIDATION
        for event in ledger.events
    )


def test_compiler_check_must_be_repeated_after_artifact_rewrite():
    requirements = infer_completion_requirements("Update proof.v")
    ledger = EvidenceLedger.from_tool_events(
        [
            _event(1, "write_file", "proof.v\nfirst version", output="wrote proof.v"),
            _event(2, "bash", "coqc proof.v", exit_code=1, output="compile error"),
            _event(3, "write_file", "proof.v\nsecond version", output="wrote proof.v"),
        ],
        requirements,
    )

    decision = ledger.evaluate()
    assert decision.can_complete is False
    assert "validation predates" in decision.reason

    ledger.record_tool_event(_event(4, "bash", "coqc proof.v"))
    decision = ledger.evaluate()
    assert decision.can_complete is True
    assert "validation evidence" in decision.reason


def test_json_write_file_then_read_records_and_validates_required_artifact():
    """Native compact tool events carry write_file arguments as JSON."""
    path = "/workspace/results/paper_digest.md"
    ledger = EvidenceLedger.from_tool_events(
        [
            _event(1, "write_file", json.dumps({"path": path, "content": "# Verified digest\n"}), output=f"wrote {path}"),
            _event(2, "read_file", json.dumps({"path": path}), output="# Verified digest\n"),
        ],
        CompletionRequirements(required_artifacts=(path,), verifier_required=True),
    )

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.SATISFIED
    assert decision.can_complete is True
    assert any(
        event.kind == EvidenceKind.ARTIFACT_MUTATION and event.artifact_path == path
        for event in ledger.events
    )


def test_latest_failed_mutation_invalidates_earlier_success_for_required_artifact():
    requirements = CompletionRequirements(
        required_artifacts=("/workspace/results.jsonl",)
    )
    ledger = EvidenceLedger.from_tool_events(
        [
            _event(1, "write_file", "/workspace/results.jsonl\n{\"value\": 1}\n", output="wrote results"),
            _event(2, "python", (
                "with open('/workspace/results.jsonl', 'w') as f:\n"
                "    raise RuntimeError('conversion failed')"
            ), exit_code=1, output="RuntimeError: conversion failed"),
        ],
        requirements,
    )

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.BLOCKED
    assert decision.missing_artifacts == ("/workspace/results.jsonl",)


def test_write_file_helper_script_does_not_satisfy_artifact_it_mentions():
    requirements = CompletionRequirements(
        required_artifacts=(
            "/workspace/meta_analysis.csv",
            "/workspace/cross_benchmark_comparison.png",
        )
    )
    ledger = EvidenceLedger.from_tool_events(
        [_event(1, "write_file", (
            "/workspace/download_and_analyze.py\n"
            "import pandas as pd\n"
            "pd.DataFrame().to_csv('/workspace/meta_analysis.csv')\n"
        ), output="wrote helper script")],
        requirements,
    )

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.BLOCKED
    assert decision.missing_artifacts == (
        "/workspace/meta_analysis.csv",
        "/workspace/cross_benchmark_comparison.png",
    )


def test_absolute_required_artifact_requires_exact_path_not_same_basename():
    requirements = CompletionRequirements(
        required_artifacts=("/workspace/meta_analysis.csv",)
    )
    ledger = EvidenceLedger.from_tool_events(
        [_event(1, "write_file", "/workspace/papers/meta_analysis.csv\nModel,RefCOCO-avg,ERQA\n", output="wrote nested csv")],
        requirements,
    )

    decision = ledger.evaluate()
    assert decision.status == CompletionStatus.BLOCKED
    assert decision.missing_artifacts == ("/workspace/meta_analysis.csv",)


def test_sed_in_place_edit_is_recorded_as_artifact_mutation():
    requirements = infer_completion_requirements("Update /workspace/app.py")
    ledger = EvidenceLedger.from_tool_events(
        [_event(1, "bash", "sed -i 's/VALUE = 1/VALUE = 2/' /workspace/app.py")],
        requirements,
    )

    assert any(
        event.kind == EvidenceKind.ARTIFACT_MUTATION
        and event.artifact_path == "/workspace/app.py"
        for event in ledger.events
    )


def test_evidence_records_hashes_not_raw_command_or_output():
    secret = "super-secret-value"
    ledger = EvidenceLedger.from_tool_events([_event(1, "bash", f"echo {secret}", output=secret)])

    serialized = str(ledger.to_list())
    assert secret not in serialized
    assert len(ledger.events[0].command_sha256) == 64
    assert len(ledger.events[0].output_sha256) == 64


def test_workspace_artifact_file_decides_completion_after_successful_write(tmp_path):
    (tmp_path / "empty.txt").touch()
    (tmp_path / "score_chart.png").write_text("placeholder")
    (tmp_path / "output.txt").write_text("done\n")
    for name, can_complete in [
        ("missing.txt", False),
        ("empty.txt", False),
        ("score_chart.png", False),  # not a valid PNG signature
        ("output.txt", True),
    ]:
        artifact = f"/workspace/{name}"
        ledger = EvidenceLedger.from_tool_events(
            [_event(1, "write_file", artifact, output="wrote bytes")],
            CompletionRequirements(required_artifacts=(artifact,), workspace_root=str(tmp_path)),
        )
        decision = ledger.evaluate()
        assert decision.can_complete is can_complete, name
        if not can_complete:
            assert decision.missing_artifacts == (artifact,), name


def test_exhaustion_and_awaiting_user_are_non_completion_states():
    ledger = EvidenceLedger()
    assert ledger.evaluate(exhausted=True).status == CompletionStatus.EXHAUSTED
    assert ledger.evaluate(awaiting_user=True).status == CompletionStatus.AWAITING_USER
