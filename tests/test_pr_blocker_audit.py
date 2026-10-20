import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.helpers.import_state import preserve_import_state

_SPEC = importlib.util.spec_from_file_location(
    "pr_blocker_audit", Path(__file__).resolve().parents[1] / "scripts" / "pr_blocker_audit.py"
)
audit = importlib.util.module_from_spec(_SPEC)
# @dataclass resolves annotations through sys.modules, so the script must be
# registered while it executes; cli_loader.load_script never registers it.
with preserve_import_state(_SPEC.name):
    sys.modules[_SPEC.name] = audit
    _SPEC.loader.exec_module(audit)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _fake_gh(monkeypatch, *, files_error=None):
    """Serve one PR with no file list, then its files (or raise `files_error`)."""
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            return [{"number": 5, "title": "Needs files", "files": []}]
        if files_error:
            raise files_error
        return [{"filename": "core/search.py"}]

    monkeypatch.setattr(audit, "_run_gh_json", fake_run)
    return calls

def test_parses_graphql_style_pr_json():
    prs = audit.normalize_prs(
        [
            {
                "number": 7,
                "title": "Fix auth token rotation",
                "author": {"login": "alice"},
                "url": "https://example.test/pr/7",
                "mergeStateStatus": "CLEAN",
                "reviewDecision": "REVIEW_REQUIRED",
                "updatedAt": "2026-05-30T12:00:00Z",
                "files": [{"path": "core/auth/tokens.py"}],
            }
        ]
    )

    assert prs[0].number == 7
    assert prs[0].author == "alice"
    assert prs[0].url.endswith("/7")
    assert prs[0].files == ("core/auth/tokens.py",)
    assert "Auth / users / API tokens" in prs[0].areas


def test_parses_rest_style_pr_json():
    prs = audit.normalize_prs(
        [
            {
                "number": 8,
                "title": "Improve uploads",
                "user": {"login": "bob"},
                "html_url": "https://example.test/pr/8",
                "mergeable_state": "dirty",
                "files": [{"filename": "app/documents/upload.py"}],
            }
        ]
    )

    assert prs[0].author == "bob"
    assert prs[0].url.endswith("/8")
    assert prs[0].merge_state == "dirty"
    assert prs[0].files == ("app/documents/upload.py",)


def test_parses_file_lists_as_dicts_and_strings():
    prs = audit.normalize_prs(
        [
            {
                "number": 1,
                "title": "Memory update",
                "files": ["core/memory.py", {"path": "tests/test_memory.py"}, {"filename": "docs/memory.md"}],
            }
        ]
    )

    assert prs[0].files == ("core/memory.py", "docs/memory.md", "tests/test_memory.py")


def test_missing_files_is_handled():
    prs = audit.normalize_prs([{"number": 2, "title": "No file metadata"}])

    assert prs[0].files == ()
    assert prs[0].author == "unknown"


def test_fetch_live_prs_fills_missing_files(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            return [
                {"number": 1, "title": "Has files", "files": [{"path": "core/auth.py"}]},
                {"number": 2, "title": "Needs files", "files": []},
            ]
        return [{"filename": "core/search.py"}, {"filename": "tests/test_search.py"}]

    monkeypatch.setattr(audit, "_run_gh_json", fake_run)

    payload = audit.fetch_live_prs("owner/repo")
    prs = audit.normalize_prs(payload)

    assert [pr.files for pr in prs] == [("core/auth.py",), ("core/search.py", "tests/test_search.py")]
    assert calls[-1] == ["gh", "api", "--paginate", "repos/owner/repo/pulls/2/files?per_page=100"]


def test_fetch_live_prs_keeps_missing_files_when_per_pr_fetch_fails(monkeypatch):

    def fake_run(cmd):
        if cmd[:3] == ["gh", "pr", "list"]:
            return [{"number": 3, "title": "Needs files", "files": []}]
        raise RuntimeError("rate limit")

    monkeypatch.setattr(audit, "_run_gh_json", fake_run)

    payload = audit.fetch_live_prs("owner/repo")
    prs = audit.normalize_prs(payload)

    assert prs[0].files == ()
    assert "PR #3: could not fetch changed files: rate limit" in payload["warnings"]


def test_fetch_live_prs_no_fetch_files_skips_per_pr_calls(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return [{"number": 4, "title": "Metadata only", "files": []}]

    monkeypatch.setattr(audit, "_run_gh_json", fake_run)

    payload = audit.fetch_live_prs("owner/repo", fetch_files=False)

    assert payload == [{"number": 4, "title": "Metadata only", "files": []}]
    assert len(calls) == 1


def test_fetch_live_prs_passes_limit_to_gh_pr_list(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return []

    monkeypatch.setattr(audit, "_run_gh_json", fake_run)

    audit.fetch_live_prs("owner/repo", fetch_files=True, limit=50)

    assert calls[0] == [
        "gh",
        "pr",
        "list",
        "--repo",
        "owner/repo",
        "--state",
        "open",
        "--limit",
        "50",
        "--json",
        "number,title,author,files,mergeStateStatus,reviewDecision,updatedAt,url",
    ]


def test_no_fetch_files_omits_files_from_gh_pr_list(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return []

    monkeypatch.setattr(audit, "_run_gh_json", fake_run)

    audit.fetch_live_prs("owner/repo", fetch_files=False, limit=50)

    assert calls[0][-1] == "number,title,author,mergeStateStatus,reviewDecision,updatedAt,url"


def test_fetch_live_prs_caps_rest_fallback_by_limit(monkeypatch):

    def fake_run(cmd):
        if cmd[:3] == ["gh", "pr", "list"]:
            raise RuntimeError("graphql unavailable")
        return [
            {"number": 1, "title": "A", "files": []},
            {"number": 2, "title": "B", "files": []},
            {"number": 3, "title": "C", "files": []},
        ]

    monkeypatch.setattr(audit, "_run_gh_json", fake_run)

    payload = audit.fetch_live_prs("owner/repo", fetch_files=False, limit=2)

    assert [item["number"] for item in payload] == [1, 2]


def test_offline_input_ignores_limit(tmp_path, capsys):
    path = tmp_path / "prs.json"
    path.write_text(
        json.dumps(
            [
                {"number": 1, "title": "A", "files": []},
                {"number": 2, "title": "B", "files": []},
            ]
        ),
        encoding="utf-8",
    )

    exit_code = audit.main(["--input", str(path), "--limit", "1"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Total PRs analyzed: 2" in output


def test_invalid_limit_exits_cleanly(capsys):

    with pytest.raises(SystemExit) as exc:
        audit.main(["--repo", "owner/repo", "--limit", "0"])

    assert exc.value.code == 2
    assert "must be a positive integer" in capsys.readouterr().err

def test_progress_goes_to_stderr_only_when_requested_for_live_fetches(monkeypatch, tmp_path, capsys):
    offline = tmp_path / "prs.json"
    offline.write_text(json.dumps([{"number": 6, "title": "Offline", "files": []}]), encoding="utf-8")
    _fake_gh(monkeypatch)
    monkeypatch.setattr(audit.sys.stderr, "isatty", lambda: False)
    for args, expect_list_progress, expect_files_progress in [
        (["--repo", "owner/repo", "--format", "terminal", "--progress", "always"], True, True),
        (["--repo", "owner/repo", "--progress", "auto"], False, False),
        (["--repo", "owner/repo", "--no-fetch-files", "--progress", "always"], False, False),
        (["--input", str(offline), "--progress", "always"], False, False),
    ]:
        assert audit.main(args) == 0
        captured = capsys.readouterr()
        assert "PR Blocker Audit" in captured.out, args
        assert "Fetching" not in captured.out, args
        assert ("Fetching open PR list..." in captured.err) == expect_list_progress, args
        assert ("Fetching changed files:" in captured.err) == expect_files_progress, args


def test_quiet_suppresses_progress_and_warning(monkeypatch, capsys):
    _fake_gh(monkeypatch, files_error=RuntimeError("rate limit"))

    exit_code = audit.main(["--repo", "owner/repo", "--progress", "always", "--quiet"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "PRs missing changed-file metadata: 1" in captured.out
    assert captured.err == ""


def test_markdown_output_file_has_no_progress_or_ansi(monkeypatch, tmp_path, capsys):
    output_path = tmp_path / "report.md"
    _fake_gh(monkeypatch)

    exit_code = audit.main(["--repo", "owner/repo", "--output", str(output_path), "--progress", "always"])
    captured = capsys.readouterr()
    report = output_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert captured.out == ""
    assert "Fetching changed files:" in captured.err
    assert "Fetching changed files:" not in report
    assert not ANSI.search(report)


def test_docs_tooling_and_test_only_prs_are_docs_tooling():
    for files, title in [
        (["scripts/odysseus-mail", "tests/test_email.py"], "CalDAV sync"),
        (["docs/pr-blocker-audit.md"], "Update docs"),
        (["scripts/pr_blocker_audit.py"], "Tooling script update"),
        (["README.md"], "README update"),
    ]:
        assert "Docs / tooling / tests" in audit.classify_areas(files, title), files
    assert "Email / CalDAV" in audit.classify_areas(["scripts/odysseus-mail", "tests/test_email.py"], "CalDAV sync")


def test_runtime_plus_test_file_is_not_docs_tooling():

    areas = audit.classify_areas(["routes/memory_routes.py", "tests/test_memory_routes.py"], "Fix memory route")

    assert "Memory / RAG / vector store" in areas
    assert "Docs / tooling / tests" not in areas


def test_memory_owner_scope_leak_is_not_classified_as_auth():

    areas = audit.classify_areas(
        ["routes/memory_routes.py", "services/memory/store.py"],
        "fix: memory route leaks another user's session",
    )

    assert "Memory / RAG / vector store" in areas
    assert "Auth / users / API tokens" not in areas


def test_bearer_token_auth_path_is_classified_as_auth():

    areas = audit.classify_areas(
        ["core/auth.py", "routes/auth_routes.py"],
        "fix: deleted users keep API access through bearer tokens",
    )

    assert "Auth / users / API tokens" in areas


def test_generic_security_file_is_not_classified_as_auth():

    areas = audit.classify_areas(
        ["tests/test_email_linkify_security_js.py"],
        "Harden email HTML URL sanitization",
    )

    assert "Email / CalDAV" in areas
    assert "Auth / users / API tokens" not in areas


def test_hot_file_overlap_detection():
    prs = audit.normalize_prs(
        [
            {"number": 1, "title": "A", "files": ["core/search.py"]},
            {"number": 2, "title": "B", "files": ["core/search.py", "tests/test_search.py"]},
            {"number": 3, "title": "C", "files": ["core/other.py"]},
        ]
    )

    assert audit.hot_files(prs) == [("core/search.py", [1, 2])]


def test_possible_duplicate_grouping():
    prs = audit.normalize_prs(
        [
            {"number": 1, "title": "Fix auth token refresh", "files": ["core/auth.py", "tests/test_auth.py"]},
            {"number": 2, "title": "Repair auth token refresh", "files": ["core/auth.py", "tests/test_auth.py"]},
            {"number": 3, "title": "Improve gallery preview", "files": ["core/gallery.py"]},
        ]
    )

    groups = audit.duplicate_candidates(prs)

    assert [[pr.number for pr in group] for group in groups] == [[1, 2]]


def test_score_ranking_is_deterministic():
    prs = audit.normalize_prs(
        [
            {
                "number": 2,
                "title": "Gallery polish",
                "reviewDecision": "APPROVED",
                "updatedAt": "2026-05-20T00:00:00Z",
                "files": ["core/gallery.py"],
            },
            {
                "number": 1,
                "title": "Fix auth token owner permission",
                "mergeStateStatus": "DIRTY",
                "reviewDecision": "REVIEW_REQUIRED",
                "updatedAt": "2026-06-01T00:00:00Z",
                "files": ["core/auth.py", "tests/test_auth.py"],
            },
        ]
    )

    scored = audit.score_prs(prs, now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert [item.pr.number for item in scored] == [1, 2]
    assert scored[0].score > scored[1].score


def test_direct_bearer_token_issue_ranks_above_dirty_memory_leak():
    prs = audit.normalize_prs(
        [
            {
                "number": 1,
                "title": "fix: deleted users keep API access through bearer tokens",
                "mergeStateStatus": "CLEAN",
                "files": ["core/auth.py", "routes/auth_routes.py"],
            },
            {
                "number": 2,
                "title": "fix: memory route leaks another user's session",
                "mergeStateStatus": "DIRTY",
                "files": ["routes/memory_routes.py", "services/memory/store.py"],
            },
        ]
    )

    scored = audit.score_prs(prs, now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert [item.pr.number for item in scored] == [1, 2]
    assert scored[0].score > scored[1].score


def test_dirty_state_is_caution_text_not_priority_boost():
    dirty_memory = audit.normalize_prs(
        [
            {
                "number": 2,
                "title": "fix: memory route leaks another user's session",
                "mergeStateStatus": "DIRTY",
                "files": ["routes/memory_routes.py", "services/memory/store.py"],
            }
        ]
    )[0]
    clean_auth = audit.normalize_prs(
        [
            {
                "number": 1,
                "title": "fix: deleted users keep API access through bearer tokens",
                "mergeStateStatus": "CLEAN",
                "files": ["core/auth.py", "routes/auth_routes.py"],
            }
        ]
    )[0]

    dirty_score = audit.score_pr(dirty_memory, audit.Counter(), datetime(2026, 6, 3, tzinfo=timezone.utc))
    clean_auth_score = audit.score_pr(clean_auth, audit.Counter(), datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert dirty_score.score < clean_auth_score.score
    assert any("caution: merge state DIRTY" == reason for reason in dirty_score.reasons)


def test_markdown_contains_expected_sections_and_no_ansi():
    prs = audit.normalize_prs([{"number": 1, "title": "Fix search", "files": ["core/search.py"]}])

    report = audit.render_markdown(prs)

    assert "# PR Blocker Audit" in report
    assert "## Executive summary" in report
    assert "## Locked code areas" in report
    assert "## Hot files" in report
    assert "## Review / blocker priorities" in report
    assert "## Duplicate candidates" in report
    assert "## Safer areas for new work" in report
    assert not ANSI.search(report)


def test_report_includes_missing_file_metadata_count():
    prs = audit.normalize_prs(
        [
            {"number": 1, "title": "Fix search", "files": ["core/search.py"]},
            {"number": 2, "title": "No files"},
        ]
    )

    markdown = audit.render_markdown(prs)
    terminal = audit.render_terminal(prs, use_color=False)

    assert "- PRs missing changed-file metadata: 1" in markdown
    assert "PRs missing changed-file metadata: 1" in terminal


def test_overlap_summary_uses_hot_files_not_huge_clusters():
    prs = audit.normalize_prs(
        [{"number": number, "title": f"PR {number}", "files": ["common.py"]} for number in range(1, 25)]
    )

    report = audit.render_terminal(prs, use_color=False)

    assert "Main overlap drivers: common.py (24 PRs)" in report
    assert "Largest overlap clusters" not in report
    assert "24 PRs (#1, #2" not in report


def test_long_pr_number_lists_are_truncated():

    assert audit._format_pr_numbers(range(1, 16), limit=4) == "#1, #2, #3, #4, ... (+11 more)"


def test_other_locked_area_sorts_after_classified_critical_area():
    payload = [
        {"number": 1, "title": "Fix auth token", "files": ["core/auth.py"]},
        {"number": 2, "title": "Fix auth login", "files": ["routes/auth.py"]},
        {"number": 3, "title": "Fix auth permission", "files": ["tests/test_auth.py"]},
        {"number": 4, "title": "Fix auth security", "files": ["docs/auth.md"]},
    ]
    payload.extend({"number": number, "title": f"Unclassified {number}"} for number in range(5, 25))
    prs = audit.normalize_prs(payload)

    locked = audit.locked_areas(prs, audit.score_prs(prs))

    assert locked[0]["area"] == "Auth / users / API tokens"
    assert locked[-1]["area"] == "Other / unclassified"
    assert locked[-1]["why"] == "20 PRs, mostly missing changed-file metadata"


def test_terminal_render_color_modes():
    prs = audit.normalize_prs(
        [
            {"number": 1, "title": "Fix search", "mergeStateStatus": "CLEAN", "files": ["core/search.py"]},
            {"number": 2, "title": "Search follow-up", "mergeStateStatus": "DIRTY", "files": ["core/search.py"]},
        ]
    )

    colored = audit.render_terminal(prs, use_color=True)
    plain = audit.render_terminal(prs, use_color=False)

    assert ANSI.search(colored)
    assert not ANSI.search(plain)


def test_terminal_hot_files_respects_top():
    prs = audit.normalize_prs(
        [
            {"number": 1, "title": "A", "files": ["a.py", "b.py"]},
            {"number": 2, "title": "B", "files": ["a.py", "b.py"]},
            {"number": 3, "title": "C", "files": ["b.py"]},
        ]
    )

    report = audit.render_terminal(prs, top=1, use_color=False)

    assert "Hot files" in report
    assert "- b.py" in report
    assert "- a.py" not in report


def test_terminal_truncates_long_title_but_markdown_keeps_it():
    long_title = "Fix search " + "very-long-detail " * 12
    prs = audit.normalize_prs([{"number": 1, "title": long_title, "files": ["core/search.py"]}])

    terminal = audit.render_terminal(prs, use_color=False)
    markdown = audit.render_markdown(prs)
    short_title = audit.shorten_text(long_title)

    assert short_title in terminal
    assert long_title not in terminal
    assert long_title in markdown


def test_cli_color_flags_control_ansi(tmp_path, capsys):
    path = tmp_path / "prs.json"
    path.write_text(json.dumps([{"number": 1, "title": "Fix search", "files": ["core/search.py"]}]), encoding="utf-8")
    for flag, expect_ansi in [("--color", True), ("--no-color", False)]:
        args = ["--format", "terminal", flag, "--input", str(path)]
        if flag == "--color":
            args.insert(3, "always")
        assert audit.main(args) == 0
        assert bool(ANSI.search(capsys.readouterr().out)) == expect_ansi, flag


def test_color_auto_requires_terminal_and_support(monkeypatch):
    args = audit.argparse.Namespace(format="terminal", color="auto", output=None)

    monkeypatch.setattr(audit.sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setitem(audit.os.environ, "TERM", "xterm-256color")
    assert audit.should_use_color(args)

    monkeypatch.setitem(audit.os.environ, "NO_COLOR", "1")
    assert not audit.should_use_color(args)


def test_color_output_file_and_markdown_disable_ansi(monkeypatch):
    monkeypatch.setattr(audit.sys.stdout, "isatty", lambda: True)
    monkeypatch.setitem(audit.os.environ, "TERM", "xterm-256color")

    output_args = audit.argparse.Namespace(format="terminal", color="auto", output="report.txt")
    markdown_args = audit.argparse.Namespace(format="markdown", color="always", output=None)

    assert not audit.should_use_color(output_args)
    assert not audit.should_use_color(markdown_args)


def test_invalid_json_handled_cleanly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{bad json", encoding="utf-8")

    exit_code = audit.main(["--input", str(path)])

    assert exit_code == 1


def test_empty_input_handled_cleanly(tmp_path, capsys):
    path = tmp_path / "prs.json"
    path.write_text(json.dumps([]), encoding="utf-8")

    exit_code = audit.main(["--input", str(path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Total PRs analyzed: 0" in output
    assert "No PRs to rank." in output


# --- JSON format tests ---

JSON_PRS = [
    {
        "number": 1,
        "title": "Fix auth token rotation",
        "author": {"login": "alice"},
        "url": "https://example.test/pr/1",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "REVIEW_REQUIRED",
        "updatedAt": "2026-05-30T12:00:00Z",
        "files": [{"path": "core/auth.py"}, {"path": "tests/test_auth.py"}],
    },
    {
        "number": 2,
        "title": "Fix auth login flow",
        "author": {"login": "bob"},
        "url": "https://example.test/pr/2",
        "mergeStateStatus": "DIRTY",
        "reviewDecision": "CHANGES_REQUESTED",
        "updatedAt": "2026-05-28T10:00:00Z",
        "files": [{"path": "core/auth.py"}, {"path": "routes/auth_routes.py"}],
    },
]


def test_json_report_shape(tmp_path, capsys):
    path = tmp_path / "prs.json"
    path.write_text(json.dumps(JSON_PRS), encoding="utf-8")

    exit_code = audit.main(["--input", str(path), "--format", "json", "--color", "always"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert not ANSI.search(output)
    parsed = json.loads(output)
    assert set(parsed.keys()) == {
        "summary",
        "locked_areas",
        "hot_files",
        "review_priorities",
        "duplicate_candidates",
        "safer_areas",
    }
    assert parsed["summary"]["total_prs_analyzed"] == 2
    assert set(parsed["summary"]) >= {
        "unique_files_touched",
        "prs_missing_changed_file_metadata",
        "main_overlap_drivers",
        "highest_risk_areas",
        "recommended_first_review_target",
    }
    first = parsed["review_priorities"][0]
    assert set(first.keys()) >= {"rank", "number", "score", "title", "url", "merge_state", "review_decision", "reasons"}
    assert first["rank"] == 1
    assert isinstance(first["reasons"], list)
    hot = parsed["hot_files"]
    assert hot[0]["file"] == "core/auth.py"
    assert hot[0]["pr_count"] == 2
    assert set(hot[0]["pr_numbers"]) == {1, 2}


def test_json_output_file_excludes_progress_and_ansi_in_live_output_file(monkeypatch, tmp_path, capsys):
    output_path = tmp_path / "report.json"

    def fake_run(cmd):
        if cmd[:3] == ["gh", "pr", "list"]:
            return JSON_PRS
        return []

    monkeypatch.setattr(audit, "_run_gh_json", fake_run)

    exit_code = audit.main(
        ["--repo", "owner/repo", "--format", "json", "--output", str(output_path), "--progress", "always"]
    )
    captured = capsys.readouterr()
    report = output_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert captured.out == ""
    assert "Fetching open PR list..." in captured.err or "Fetching changed files" in captured.err
    parsed = json.loads(report)
    assert set(parsed.keys()) == {
        "summary",
        "locked_areas",
        "hot_files",
        "review_priorities",
        "duplicate_candidates",
        "safer_areas",
    }
    assert not ANSI.search(report)
    assert "Fetching" not in report


def test_json_output_is_deterministic():
    prs = audit.normalize_prs(JSON_PRS)
    first = audit.render_json(prs)
    second = audit.render_json(prs)

    assert first == second
    assert isinstance(json.loads(first), dict)


def test_json_empty_input_handled_cleanly(tmp_path, capsys):
    path = tmp_path / "prs.json"
    path.write_text(json.dumps([]), encoding="utf-8")

    exit_code = audit.main(["--input", str(path), "--format", "json"])
    output = capsys.readouterr().out

    assert exit_code == 0
    parsed = json.loads(output)
    assert parsed["summary"]["total_prs_analyzed"] == 0
    assert parsed["hot_files"] == []
    assert parsed["review_priorities"] == []
