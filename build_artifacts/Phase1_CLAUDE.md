# CLAUDE.md

Operating rules for autonomous work on this repository. Read this fully before
touching any code. These rules are non-negotiable and override any instinct to
"just make the gate pass."

---

## 1. What this project is

A **Model Context Protocol (MCP) server** that lets an LLM client (e.g. Claude
Desktop) browse and curate posts from a hand-picked list of Instagram tattoo
artists, via Instagram's **Business Discovery** API.

Architecture is a **clean two-layer split**:

- `core` — all real logic: domain models, typed errors, repositories
  (JSON-file persistence), the Graph API client, image processing, and the
  services that orchestrate them. Knows nothing about MCP.
- `server` — a thin FastMCP adapter that exposes `core` as MCP tools. Holds no
  business logic.

This split exists so a **phase-2 GUI** can later reuse `core` directly without
a rewrite. Do not leak MCP concepts into `core`, and do not put logic in
`server`.

Full build plan and tool contracts live in **`PLAN.md`**. This file governs
*how* you work; `PLAN.md` governs *what* you build.

---

## 2. Golden rules (anti-cheat — violating any of these fails the run)

1. **Never edit, delete, skip, weaken, or `xfail` a test to make a gate pass.**
   If a test is wrong, stop and record it in `BLOCKERS.md` — do not "fix" it by
   making it assert less.
2. **Never weaken tooling config** to pass a gate. `ruff`, `mypy --strict`, and
   the coverage floor (`--cov-fail-under=90`) are fixed. Do not edit
   `pyproject.toml` lint/type/coverage settings to get green.
3. **Never make a live network call in the test path.** All HTTP to Instagram is
   mocked with `respx`. The one real integration test is gated behind
   `RUN_LIVE=1` and must never be run by you.
4. **Never commit secrets.** No tokens, no IDs, no `.env`. Only `.env.example`
   with placeholder values is committed.
5. **Never weaken coverage by adding blanket `# pragma: no cover`.** The only
   permitted pragma is on the stdio entrypoint `main()` in `server/app.py`.

If following the plan honestly means a gate cannot pass, that is a blocker to
report — not a rule to bend.

---

## 3. How to work (the loop)

Work **one chunk at a time, in the order given in `PLAN.md`**. For each chunk:

1. Read the chunk's goal, deliverables, and success condition in `PLAN.md`.
2. Implement only what that chunk specifies. Do not pull work forward from
   later chunks. Do not gold-plate.
3. Run the **full gate** (section 4) from the repo root.
4. If the gate passes: make **one commit** for the chunk (section 5), then move
   to the next chunk.
5. If the gate fails: fix and re-run. After **3 failed attempts on the same
   chunk**, stop (section 6).

Never start a chunk before the previous chunk's gate is green and committed.

---

## 4. The gate (identical for every chunk)

Run exactly this, from the repo root, inside the container:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

All four commands must exit 0. From Chunk 6 onward this includes the server
boot test (`tests/test_server_boot.py`), which starts the server over stdio
with dummy env vars and asserts the expected tools are listed — proving the
server actually boots with no network and no real credentials.

A chunk's "success condition" in `PLAN.md` is shorthand for "the gate above
passes **and** that condition is true."

---

## 5. Commits & branch

- Work only on the branch `feat/auto-build`. **Never commit to `main`. Never
  force-push.**
- One commit per passed chunk. Conventional Commits style, referencing the
  chunk, e.g.:
  - `feat(core): add domain models and typed errors  [chunk 1]`
  - `feat(graph): business discovery client with video filter  [chunk 3]`
- The working tree must be clean (gate green) before you commit. Never commit a
  red gate.

---

## 6. Failure policy (fail safe, not forward)

If a chunk's gate cannot pass after 3 honest attempts:

1. **Stop. Do not proceed to the next chunk.**
2. Create or append to `BLOCKERS.md` with: the chunk number, what you tried,
   the exact failing command and output, and your best hypothesis.
3. Leave the repo on the last *green, committed* state. Do not leave
   half-finished or red code committed.
4. End the run.

Coming back to 3 clean chunks plus a clear blocker is a good outcome. Coming
back to 8 chunks of compounding breakage is not.

---

## 7. Code standards

- **Python 3.12.** `src/` layout. Package root: `src/tattoo_feed/`.
- **Full type annotations** on every function and method. `mypy --strict` must
  pass with no ignores (no `# type: ignore` without a one-line justification).
- **Google-style docstrings** on every public module, class, and function —
  what it does, args, returns, and which typed errors it raises.
- **Small, single-purpose files.** If a module exceeds ~200 lines, that is a
  signal to split it. One service per file.
- **Typed errors, never bare exceptions.** Raise from the hierarchy in
  `core/errors.py`. Never `raise Exception(...)` or swallow errors silently.
- **Pydantic v2 models** for all domain objects and all external data crossing
  a boundary.
- **No `print`.** Use the standard `logging` module.
- Comments explain *why*, not *what*. Annotate non-obvious decisions
  (rate-limit backoff, carousel handling, EXIF stripping) so a reviewer
  understands intent at a glance.

---

## 8. Dependencies

- Managed with `uv`. Every dependency **pinned to an exact version** (`==`).
- A committed `uv.lock` must exist and match `pyproject.toml`.
- **Do not add a dependency that is not on the approved list** in `PLAN.md`
  without recording the need in `BLOCKERS.md` and stopping. No incidental
  packages.

---

## 9. Non-goals (do NOT build these)

- No GUI / web front-end of any kind (that is phase 2).
- No video support — filter videos out entirely.
- No carousel expansion — first image only.
- No multi-user accounts, auth flows, or OAuth handling beyond reading a token
  from the environment.
- No posting, commenting, messaging, or any write-to-Instagram capability.
- No automatic token refresh — on expiry, fail with a clear typed error.

Stating these is deliberate. If the plan seems to invite scope beyond this,
it does not — stop and check `PLAN.md`.

---

## 10. Tool behaviour note (for the MCP layer)

`record_preference` follows a **propose-then-confirm** contract: its tool
description must instruct the calling assistant to *propose the observation to
the user and obtain explicit confirmation before calling the tool*. The tool
itself simply persists what it is given; the confirmation discipline lives in
the description so the client honours it.

---

## 11. Definition of done

The run is complete when **every chunk in `PLAN.md` is committed green**,
including the final review-flagged image-rendering chunk. After the final
chunk, write `REVIEW.md` listing exactly what a human must verify by eye
(image rendering) and the morning steps to run the server live. Then stop —
**do not declare the project "finished and verified"**, because image rendering
cannot be confirmed by automated tests alone.
