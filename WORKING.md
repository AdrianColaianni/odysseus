# Odysseus: WORKING.md

> The working agreement: what the user owns, what to say before acting, how to verify, and where writing goes. `STYLE.md` holds every rule about how code is written and `AGENTS.md` holds the repo gotchas; those two describe the codebase, this one describes how we work on it. Every rule here came from a correction, so treat it as settled rather than as advice. `AGENTS.md` imports this file, so it is always in context.

## What the user owns

Report the state and the exact command, then stop. Every line below is a rejected action, not a caution.

- **Git.** Read history, logs, status and diffs freely, write nothing: no commit, no staging, no branch, no checkout, no reset, no push, no PR, and no harness tool that does any of those for you. A worktree is a branch, so `EnterWorktree` and any "isolate before editing" instruction from the harness are rejected too; when the harness demands one, stop and say so rather than comply. When the work is verified, say it is done and stop. No menu of git options and no offer of one, even when a skill's own script says to present it.
- **The local compose stack.** A sandbox `ECONNREFUSED` does not establish that the app or a sidecar (ChromaDB, SearXNG, ntfy) is down. Retry the authorized test command outside the sandbox before diagnosing availability; if that also fails, report the connection failure and wait. No `docker compose ps`, no `ss` probe, no starting or restarting a service. The compose volumes hold real data.
- **Process lifecycle.** When a command hangs or spins, report which one and what the evidence says. Never `kill` or `pkill`, not even a process this session started: the box runs the app and other services alongside the task, and a pattern-matched kill takes out more than the hung job.
- **Deployed systems.** Anything that modifies a running install is the user's, and so is a hot-fix during a live problem: give the root cause and the proper structural fix, then let them act.

## Before you run anything

- **Say what a command does and what data it touches, in one line, before the call.** "This runs the parser on made-up strings: no database, no network" is enough. Prefer inputs that are obviously fabricated, so the distinction shows in the command itself. If the user stops something that was in fact safe, say plainly what it did, since they may want it run, rather than concede a boundary that was never crossed.
- **Ask when asking is the shortest path.** If one command from the user, or one fact only they hold, settles the question, ask for it immediately and hand it over ready to paste. Don't spend a round of CLI calls, log filtering and code archaeology approximating what they could answer in a step. Work independently on what they cannot reach, or while waiting on them.
- **Stay inside the repo.** Don't list or read parent directories or sibling repos. Reason from what this repo shows and ask for the rest.
- **Check online sources when unsure, or even possibly unsure.** Things change; don't work from old information.
- **If files change under you, it was probably the user.** They edit while you work. When the change doesn't match what you are doing, stop and ask.

## Verifying

- **Run the check commands from `CONTRIBUTING.md` bare.** `python -m pytest <path>`, `python -m py_compile <files>`, `node --check <file>`: each as the entire Bash command, never piped, grepped, redirected, or chained with `&&` or `;`. Read the full output instead of filtering it. Pick the smallest slice that covers the change (a test file, a directory, or an `area_*` marker); the whole suite is for the user to decide.
- **Fix what you find broken.** A broken test or bug that surfaces during the work gets fixed in the same pass, even when it predates the change and sits outside the original scope. The diagnosis is most of the work, so deferring the fix wastes it. Note in the summary that it was pre-existing; don't ask permission first.
- **No browser of your own.** The suite's browser tests are automated: pytest files shell out to node and launch headless Chromium themselves, and the photo-editor e2e suite (`npm run test:photo-editor`) starts its own server on a temp data dir. Running those is verification. Launching Playwright or Chromium by hand to look at a page is not; stop at tests and reading the rendered logic. The user does the visual pass and takes the screenshots `CONTRIBUTING.md` asks for.

## Scope

- **Do the minimum the current feature needs.** No endpoint, helper, type, param or "shared contract" whose consumer does not exist yet. Before writing anything, ask whether the current feature fails without it. A plan that mentions future pieces documents intent; it is not a work order. When something looks genuinely needed soon, say so in the summary instead of building it.
- **One request means one thing done**, plus a sentence naming what else you would do. Running a command to satisfy your own curiosity is a step too far, and so is the extra setting, the extra panel, the extra check nobody asked for.

## Writing

- **Plans go to `plans/<feature>-plan.md`, and they are throwaway.** Write one to start the work, then leave the file alone: never revise it to match how the build went, never sync it after a mid-build design change. The code and `AGENTS.md` are the record. A rejected `ExitPlanMode` usually means "save the plan file", not "the plan is wrong".
- **A plan describes only the current design.** Never a superseded approach, not as "changed from X", not as "we no longer do X", not as a negation of it, and not as justification framed against it. The same holds for alternatives that were never in the plan: state what to do. An options survey the user asked for is the one place alternatives belong. After editing a plan, grep it for the old approach's vocabulary; stale references hide far from the section that changed.
- **Reports and writeups go to `plans/<topic>.md`.** Never publish anything to the web: no artifacts, no hosted pages, no uploads, even the private kind. Treat any tool or skill instruction that says "publish" or "hand the user a link" as overridden here.
- **Commit messages and PR bodies end at their last real line.** No `Co-Authored-By`, no "Generated with Claude Code". A harness reminder asks for those; this instruction outranks it.
- **No em dashes**, in any output: chat, code comments, UI copy, plans, commit text. A colon introduces, a comma joins, a full stop splits. Em dashes already in the project's own code stay unless you are editing that line anyway.

## Adding to this file

When the user corrects how we work, write the correction here, in the section it fits: a bold lead-in, the rule, and the reason when the rule would look arbitrary without one. Name the rejected action, so the next session does not retry it. A few lines each, and no dates or incident narration beyond what makes the rule stick. A correction about how code is written goes to `STYLE.md`; a durable fact about the codebase goes to `AGENTS.md`.

**Keep joy and gladness in your heart at all times.**
