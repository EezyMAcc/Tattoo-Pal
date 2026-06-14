# REVIEW.md — Morning verification

Pre-shaped checklist for reviewing the overnight build. Work top to bottom.
The loop should fill in the two bracketed sections at the end before stopping.

-----

## 0. First glance (30 seconds)

- [ ] Is there a `BLOCKERS.md`? If yes, read it first — it tells you which chunk
  stopped and why. Everything below still applies to the chunks that did land.
- [ ] `git log --oneline` on `feat/auto-build` — expect one clean commit per
  completed chunk (Chunk 0 → 8), newest last.
- [ ] Working tree clean? `git status` should show nothing uncommitted.

## 1. Gate still green (2 minutes)

Re-run the full gate yourself, in the container, to confirm nothing was left red:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

- [ ] All four exit 0. Coverage ≥ 90%.

## 2. Go live (the first real Instagram call)

This is the first time real credentials and the real API are used — the loop
never did this.

- [ ] Copy `.env.example` to `.env` and fill in your real `IG_ACCESS_TOKEN` and
  `IG_USER_ID`. (`.env` is gitignored — confirm it is **not** staged.)
- [ ] Optionally run the live integration test: `RUN_LIVE=1 uv run pytest -k live`.
- [ ] Start the server and connect it from your MCP client (e.g. Claude Desktop).
  It should boot and list every tool from PLAN.md §6.

## 3. Functional smoke test (chat with it)

- [ ] `add_artist` with a real tattoo-artist handle you follow → succeeds.
- [ ] `add_artist` with a personal (non-professional) account → fails *cleanly*
  with a readable error, not a stack trace.
- [ ] `get_feed` → returns recent posts, newest-first, no videos present.
- [ ] `next_inspiration` → returns one post you haven’t seen; calling it again
  gives a *different* post.
- [ ] `save_to_inspiration` then `list_inspiration` → the saved item is there,
  in save order, with the artist handle attached.
- [ ] `record_preference` → the assistant **proposes and asks you to confirm**
  before writing (propose-then-confirm). Then `get_preference_summary`
  returns it.

## 4. THE EYEBALL CHECK (image rendering — tests cannot verify this)

This is the one thing automated gates could not confirm. Look with your eyes:

- [ ] `next_inspiration` actually **displays the image inline** in your client.
- [ ] The image is the **right image** for that post (cross-check the permalink).
- [ ] Orientation is correct (not rotated/flipped — EXIF was stripped).
- [ ] It’s a reasonable preview size (≤ 640px long edge), not full-res or tiny.
- [ ] A carousel post shows its **first** image (not a broken/blank frame).

If any of these is off, it’s almost certainly isolated to `imaging.py` or the
Chunk 8 wiring in `server/app.py` — the rest of the system is gate-verified.

## 5. Code review pass (it’s a portfolio piece)

Skim with a reviewer’s eye — this repo may go in front of an interviewer:

- [ ] `core` has zero MCP imports; `server/app.py` has zero business logic.
- [ ] Files are small and single-purpose; names are clear.
- [ ] Docstrings + type hints throughout; errors are typed, never bare.
- [ ] README explains setup, design decisions, and limitations honestly.
- [ ] No secrets, no `.env`, no `data/` committed.

## 6. Phase-2 readiness (sanity, not a task)

- [ ] Could a GUI import `core` and call the services directly, with no MCP in
  the way? If yes, the seam held and the Inspiration/Feed/Artists tabs will
  bolt straight on.

-----

## Loop fills these in before stopping

**Chunks completed:** 0–8, all green. One commit per chunk on `feat/auto-build`,
each passing the full gate (ruff format + ruff check + mypy --strict + pytest)
**inside the `tattoo-feed-dev` container, at 100% coverage** (floor is 90%). No
`BLOCKERS.md` — nothing blocked. Two extra non-chunk commits precede chunk 0:
`chore: init` (pre-existing) and `chore: add governance docs and Docker dev
harness` (CLAUDE.md, PLAN.md, REVIEW.md, Dockerfile, .dockerignore, run-loop.sh).

**Anything I flagged for you:**

- **Image rendering is NOT verified.** Automated tests only assert the image
  block is *structurally* valid (base64, `image/jpeg`, non-zero bytes, long edge
  ≤640). Whether it actually displays — and right-way-up — is section 4's job.
  The EXIF fixture uses orientation 6, so pay attention to whether real photos
  come back correctly oriented (not sideways).

- **Graph error-code mapping is best-effort and unverified against the live
  API.** All HTTP is mocked, so the mapping from Instagram errors to typed
  errors uses documented codes/subcodes (token=190, rate-limit∈{4,17,32},
  not-professional subcode 2207013, not-found subcode 2207006). The first time
  you hit a *real* error (e.g. add a personal account, or let the token expire),
  confirm it maps to the right typed error and a readable message. If Instagram's
  actual codes differ, the mapping in `graph/client.py` is the one place to tweak.

- **Two deliberate deviations from PLAN §6 contracts (UX calls):**
  1. `remove_artist`, `remove_from_inspiration`, and `reset_seen` return a short
     confirmation *string* rather than `None`, so the chat client shows something
     useful. Still thin wrappers, no logic.
  2. `save_to_inspiration(post_id)` resolves the post by scanning the *current
     feed* (no separate post cache). You can therefore only save a post that's
     currently in the feed / was just shown by `next_inspiration`; saving an
     unknown id raises `TattooFeedError` with a clear message. Worth confirming
     this matches how you expect to use it.

- **Missing credentials raise the base `TattooFeedError`** (not a dedicated
  `ConfigError`), because PLAN §5 fixes the error hierarchy. The message tells
  you to copy `.env.example` to `.env`.

- **Dependency versions** were pinned to whatever was latest-stable in the build
  container at install time (notably `mcp==1.27.2`, `pydantic==2.13.4`,
  `Pillow==12.2.0`, `httpx==0.28.1`; dev: `ruff==0.15.17`, `mypy==2.1.0`,
  `pytest==9.1.0`). All exact-pinned; `uv.lock` is committed.

- **`.venv` gotcha:** the gate ran in the Linux container, so the `.venv` in this
  folder is Linux-built. If you re-run the gate directly on macOS, do a fresh
  `uv sync` first (the committed `uv.lock` is platform-independent; the `.venv`
  is gitignored).