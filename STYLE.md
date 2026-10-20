# Odysseus: Code Style & Generation Guidelines

How to write code in this repo. **Read this before writing any non-trivial code.** Each rule below names a concrete decision or a concrete failure mode to avoid. When a rule and the surrounding code disagree, match the surrounding code and flag the mismatch.

Contribution rules (branch model, PR expectations, the visual style contract, where constants live) are in `CONTRIBUTING.md`, the working agreement (git, process ownership, verification) lives in `WORKING.md`, and testing rules are in `tests/TESTING_STANDARD.md`. This doc is only about *how* code is written.

## 1. Before writing anything

- **Read the neighbors first.** Open the file you're editing and 1 or 2 sibling files. Match their idioms: import style, error handling, comment density, naming, how they structure a route or a module. Consistency with the file beats any rule here.
- **Reuse before you build.** Search for an existing helper, dependency, middleware, model, or constant before writing a new one. Route helpers (`routes/*_helpers.py`), service modules (`src/`), and `src/constants.py` already hold most of what a new feature needs. A new utility that duplicates an existing one is a defect, not a feature.
- **Don't hand-roll what a package solves.** Before writing algorithmic code (color math, date handling, parsing, geometry, …), look for a package that already does it, first in the installed dependency tree, then on the registry. A new dependency is acceptable when it's established and earns its weight, but flag it rather than adding it silently (§7).
- **Make the smallest change that fully solves the problem.** Don't refactor adjacent code you weren't asked about, but don't leave a structure that no longer fits the requirements either (see §2). If a refactor is warranted, it's because requirements changed, not for taste.
- **Simplicity.** Write code that reads plainly and does what it needs to, no more.
- **If you're unsure whether an abstraction is wanted, ask or pick the obvious one and say so.** Don't silently invent a framework.

## 2. Structure & abstraction

- **Extract when copies must change together, not when they look alike.** Two copies of one invariant (ownership, auth, a shared contract) get one home at once. Code that merely looks alike stays inline until a third use shows what varies. Never extract an expression whose name says no more than its body, and inline one you find.
- **Cross-cutting concerns become dependencies or middleware, not repeated handler lines.** Auth, owner resolution, and request-derived context that every route needs belong in a shared FastAPI dependency or in `core/middleware.py`, resolved once and injected, not re-derived in each handler.
- **No premature abstraction.** Don't add an options bag, a config object, a factory, or a generic type parameter until there is a second concrete caller that needs it. Speculative flexibility is cost with no payer.
- **Nothing gets a name for one use.** A variable read from exactly one place hides its value behind a jump and buys no reuse. Derive it inline at the use site; a local reused several times in the same function is fine. The exception is anything `CONTRIBUTING.md` sends to `src/constants.py`: paths, ports, limits, and loopback URLs go there even with one reader, because deployments override them.
- **One home per fact.** When a feature needs data that already exists, widen the record that holds it or let a new actor write it. A second store mirroring the first drifts. If a new table or file survives that test, justify every field: drop any that a parent row or an existing scope check already provides.
- **Code that changes together lives together.** When one change means edits across several files, move those parts to one place. A cross-reference note (§4) is for sites that cannot move.
- **One function, one job.** If you need "and" to describe what a function does, or it exceeds ~40 lines of real logic, consider splitting, but only if the pieces are independently meaningful, not for a line count.
- **Prefer pure helpers.** Small functions that take inputs and return outputs over ones that reach into shared mutable state. Keep side effects (DB, network, filesystem, subprocess) at the edges.
- **Don't write wrappers that only forward.** A function that just calls another with the same args earns its place only by adding validation, defaults, or clarity.

## 3. Naming

- **Names say what a thing is or does, in the domain's words.** Not `helper`, `handler2`, `doStuff`, `tmp`.
- **Group routes and services by what the data is, never by which screen asked for it.** A module named after a page names nothing once a second page reads the same data.
- **No abbreviations that aren't already idiomatic here.** Spell the word out unless the surrounding code has already chosen the short form (match it).
- **Booleans read as assertions:** `is_owner`, `has_messages`, `only_matched`.
- **A single-letter name is only OK for a trivial, local, conventional binding** (`e` in an `except` clause, `c` in a short comprehension). Never for anything that lives more than a couple of lines.

## 4. Comments

A comment says what the code cannot. Length follows the fact: most take one line, some take two or three, none take a paragraph. Judge a comment by its content, never by its line count.

- **Say why, never what.** The code says what it does. When a choice looks wrong but isn't, say why so the next reader does not "fix" it. Delete narration (`# loop over the rows`).
- **Answer the one question the line raises, then stop.** Name the cause, not the consequence. The crash a line prevents, the env var that triggers the crash, and the argument that the choice is safe are all things the reader did not ask.
- **Say what else must change.** When editing this code means editing another site, name that site here: the file and symbol, never a line number, plus what the two must agree on. Put the same note at the other end, so a reader at either site finds the other. Moving the sites together (§2) beats a check, and a check beats a note: a shared constant, a typed mapping, or a test that imports both halves. Write the note only for what no check reaches.
- **No padding.** Banned outright: the story of how a bug was found, what breaks if the line is removed, a defence of the choice against one nobody proposed, a design summary, a header block, a restated ticket, commented-out code (git remembers). A comment that is all fact is the right length whatever the count.
- **Leave what you did not need to touch.** Trimming a true two-line comment to one is a change with no payer. Edit a comment when its code changes or when it is wrong.
- **Keep comments true.** Change the code a comment describes and you change the comment in the same edit.

`AGENTS.md` keeps only facts with no code home (an ops procedure, a runtime environment fact, a past incident) and facts that span so many sites that pairwise notes would number more than three. Everything else lives beside its code.

## 5. Control flow & error handling

- **Validate at the edge, then trust.** Inputs are validated once by the Pydantic model on the route. Handlers do **not** re-check that a required field is present or that an id is a string; that's already guaranteed. Redundant guards are cruft.
- **Don't defend against states that can't happen.** No `None` checks on values the types prove present, no `try/except` around code that doesn't raise. Guard real, reachable conditions only. The same goes for environments that never existed: don't hedge for a runtime or dependency version the project never supported.
- **Fail fast and loud.** Raise the right error (`HTTPException` with the correct status at the route edge, a typed exception from `core/exceptions.py` below it) at the point the invariant breaks. Don't return a sentinel that a caller has to remember to check.
- **Never swallow an error silently.** An `except` either handles the error meaningfully, logs it with context (`logger.warning` / `logger.error` with what failed), or re-raises. An empty `except` is a bug.
- **Prefer early returns / guard clauses** over deep nesting. Handle the empty/absent case up front and return.
- **Preserve deliberate behavior.** If an endpoint returns `null` vs `[]` on empty, or raises 404 vs 403, that shape is a contract a caller depends on. Don't change it incidentally while refactoring. If a change is intended, call it out.

## 6. Types & schemas

- **No `Any` where a real type will do.** Use a precise type, a `TypedDict`, a Pydantic model, or a generic. A `cast` is acceptable only when the code proves it safe, with a comment saying how.
- **Let inference work.** Don't annotate a local whose type is obvious from its initializer. Do annotate function signatures and return types when they're part of a contract or non-trivial.
- **Pydantic models are the input contract.** Define them once, near the route; subclass or compose rather than restating fields.
- **Fields that travel together are one type.** When the same few fields recur across params, models and return shapes, name the group once and pass that.
- **Derive types, don't duplicate them.** Build on an existing model or `TypedDict` rather than hand-copying shapes that can drift.

## 7. Hygiene

- **No dead code.** Remove unused imports, variables, params, and helpers in the same edit. Don't leave the old function next to the new one. If a param becomes unused after a refactor, drop it from the signature.
- **No stray `print`, `console.log`, `TODO` without an owner, or debug scaffolding** in committed code. `logger.*` for genuine logging is fine.
- **Match the existing formatting.** Don't reflow or re-quote lines you didn't change; keep diffs minimal and reviewable.
- **No new runtime dependency** for something the stdlib or an existing dep already does. If a dep is genuinely needed, flag it rather than adding it silently.

## 8. UI

The visual contract in `CONTRIBUTING.md` applies to every change under `static/`: reuse the existing CSS variables and classes, no Unicode emoji (inline SVG or plain text), `Fira Code` stays, dark theme is the default and light mode goes through the theme system. Run the app and look at the change. The rules below are about copy and structure.

- **One source for each fact.** Before adding a label, banner, bar, or sentence, find the element that already tells the user this; if one exists, add nothing. A state a banner names gets no matching row label. A single item gets no aggregate. A button that says "Resume" needs no sentence promising resume. Persistent tabs need no mirrored navigation buttons.
- **Make sections distinct.** Use neutral surfaces and dividers to separate navigation, controls and content. Concentrate accent color in a few places; avoid broad accent-tinted backgrounds. Keep text readable and labels present so color is never the only cue.
- **Short copy is a fragment with no trailing period.** A description the title already covers stays empty.
- **Add no control the user didn't ask for.** A request to make something configurable means a setting or an API flag; the frontend passes a fixed value until a screen needs otherwise.
- **Don't add parallel components.** If a similar widget already exists, extend it instead of writing a new one.

## 9. Tests

A test says what the types and the code cannot. Judge one by what goes wrong unnoticed when it is deleted: if the answer is nothing a caller depends on, delete it. The suite is large and every added test costs every run. `tests/TESTING_STANDARD.md` is the full standard; the rules below are the ones that most often go wrong.

- **Keep a test only when it pins one of five things.** A contract the types do not carry (which status code, `null` vs `[]`, a sort order, a cursor's shape, an inclusive or exclusive boundary, idempotency). A boundary (owner scope, auth, an admin guard, a flag that must go out on every call, content that must never reach a client). A derivation with a plausible wrong answer (an id derivation, bucket binning, a timezone, a merge rule, a parser, a precedence between rules), where the wrong answer is one a competent author could write. A past bug, named so the next reader recognizes the failure. Two sites that must agree, with the test importing both halves.
- **Delete a test that restates the code.** The columns an `UPDATE` lists, a mock's return value, a constant, a regex list, a one-line guard's two sides.
- **Delete a test that tests a dependency.** Pydantic rejecting bad input, SQLAlchemy building a query, the database honouring a constraint.
- **One test per branch.** A sibling that runs a kept test's branch with new data goes. One owner-scope test per dependency, not per route. One negative per rule, and only when the positive cannot fail the same way.
- **No copy assertions.** A sentence of prompt text, a UI label, a log line, generated markup. They break on every wording change and catch no bug.
- **A test must be able to fail.** Not one that calls the helper the code calls, or asserts on text the test pasted in.
- **The name states the decision pinned**, in the domain's words, so a red test reads as a sentence about the product.
- **No parametrize over data rows.** One loop in one test.
- **No shared mutable state between cases.** A test that reads what the previous one wrote breaks on reorder.
- **A test file longer than the file it tests needs a reason.**

## 10. Before you call it done

- **Run the smallest relevant checks**, per `WORKING.md`: `python -m pytest` for the area you touched, `python -m py_compile` on changed Python, `node --check` on changed JS, and `docker compose config` for compose changes. Say what you ran.
- **Re-read your own diff.** Every new line should be one you'd defend in review: it's needed, it's clear, and it isn't a repeat of something above it. Delete anything that isn't pulling weight.
- **Leave git alone.** Stage nothing, commit nothing. The user handles that.
