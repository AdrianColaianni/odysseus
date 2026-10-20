# Codebase trim plan

Apply the findings in `library/*.md`: fix the bugs, delete dead code, merge copies into one home, cut padding comments, fix the efficiency problems. Each agent owns a slice of files and works from that slice's report.

## Rules for every agent

1. Read `STYLE.md`, `WORKING.md`, `AGENTS.md`, `CONTRIBUTING.md`, then your report(s) in `library/` and `library/README.md`.
2. **Git is off limits.** No commit, stage, branch, checkout, stash, reset, or worktree. Read-only git (`git diff`, `git log`, `git status`) is fine.
3. **No processes.** Do not start, stop, or kill the app, docker, or any service. No `docker compose` commands. No browser of your own.
4. **Own your files.** Edit only files in your slice. Exceptions:
   - Tests that pin code you changed or deleted: update or delete them in the same pass.
   - Call sites of a symbol you delete or rename, anywhere in the repo: make the minimal edit.
   - For any file outside your slice, re-read it right before editing, keep the edit small, and never reformat it. Other agents edit in parallel.
   - Never edit `static/css/` unless you own it. Never edit `library/` reports, except to write your own results file.
5. **Behavior stays the same**, except for the listed bug fixes and the decisions below. A cut that changes what a user sees, and is not listed here, gets skipped and named in your results.
6. **Use the shared homes** listed below instead of writing a new helper. If you need a helper that does not exist, put it in the most natural file you own.
7. **No new dependencies.**
8. **Verify** per `WORKING.md`. Run `python -m py_compile <files>`, `node --check <file>` and `python -m pytest <path>` as bare commands, not piped or chained. Pick the smallest test slice that covers your change. Fix what breaks. If a test fails for reasons outside your slice, note it and move on.
9. **Comments:** follow STYLE §4. Cut narration, bug stories, banners and history. Keep a true why-comment. Write no em dashes.
10. **Do not split huge functions.** That includes `stream_agent_loop` and `stream_preview`. Trims inside them are fine.
11. When done, write `library/results/<slice>.md`. List what you changed, the lines removed (from `git diff --stat` on your files), the tests you ran and their results, and what you skipped and why. Keep it short, with no em dashes.

## Decisions

1. Keep `static/js`. Delete `frontend/` and its build, check and test apparatus, its CI steps and `docs/frontend-architecture/`.
2. In `scripts/`, delete the training and eval files with zero references anywhere. Keep harness files that tests or other kept files reference.
3. In `src/agent_loop.py`:
   - Delete the canned answers (`_qwen_no_tool_boundary_answer`, `_notes_general_definition_answer`).
   - Delete the benchmark-shaped web hacks (fuel converter, cat foam, snail, battery and hand-washing rewrites, dictionary filter).
   - Remove the hardcoded "Best, Alex" sign-off.
   - Keep the phrase routers and `_ODY_QWEN_TEXT_FIXES`: the user runs Qwen locally.
4. Delete `routes/embedding_routes.py` and its mount.
5. In `static/js/modalManager.js`, drop the chain-physics dock mode. Keep the trash zone.

## Shared homes

The foundations step adds these before the area agents start. Use them.

- `src/constants.py`: `APP_PORT`, the single default port. Use it for every port default and loopback URL.
- `core/database.py` `get_db`: the FastAPI DB-session dependency. Use `db: Session = Depends(get_db)` instead of `SessionLocal()` with `try/finally`.
- `src/auth_helpers.py`: `get_owned_or_404(db, Model, id, owner)` for "get row or 404, then check the owner". Keep each route's current anonymous-user rule. Unify a rule only where the report shows the current one is a bug.
- `static/js/ui.js` `esc`: the one HTML escaper. It escapes `& < > " '`.
- `src/url_safety.py`: the one home for SSRF checks and the pinned-IP transport. The src-other agent consolidates it.
