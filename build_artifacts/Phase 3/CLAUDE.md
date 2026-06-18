# CLAUDE.md — Phase 3 governance (the auth-wiring refactor)

Operating rules for the **third** autonomous `/loop` build on this repo: a
**behaviour-preserving refactor** that removes the module-level `FastMCP` global
and moves OAuth onto the SDK's public constructor parameters. Read this fully
before touching code. These rules are non-negotiable and override any instinct to
"just make the gate pass."

*What* to build lives in the root `PLAN.md`. *Why*, and the success criteria, live
in `scratchpads/phase-3-motivation.md` (with the decision detail in
`scratchpads/removing-the-global.md` and the problem anatomy in
`scratchpads/auth-wiring-seam.md`). The verified external contracts remain in
**`build_artifacts/Phase 2/Phase2_RESEARCH.md`** — phase 3 introduces no new
external contracts (see §6). This file governs *how* you work.

---

## Supersession — this file governs; phases 1 and 2 are archived

The phase-1 docs live in `build_artifacts/Phase 1/` (`Phase1_*`); the phase-2 docs
in `build_artifacts/Phase 2/` (`Phase2_*`, including `Phase2_CLAUDE.md`,
`Phase2_PLAN.md`, `Phase2_RESEARCH.md`, `Phase2_REVIEW.md`). They are the
**historical record** — do not move, edit, delete, or follow them.

This root `CLAUDE.md` (with the root `PLAN.md`) is the **phase-3 governance** and
is what the harness loads. Where any archived doc conflicts with these, **these
win.** The branch is **`refactor/auth`**, off `main`.

---

## Where the build runs — inside the dev container

The loop and the gate run **inside the dev image** (`tattoo-feed-dev`, from the
root `Dockerfile`), exactly as phases 1–2 did — git, Node, `uv`, Claude Code, with
**only this project mounted** at `/workspace`.

- Start it with `./run-loop.sh` (mounts `$PWD` → `/workspace`, nothing else).
- The full gate (§4) runs in this container.
- **No production secrets enter the build container.** The test suite is hermetic
  (§1.3); the refactor needs no Instagram / IdP / ngrok credentials — only Claude
  Code's own auth. Do not pass `IG_*`, IdP, or ngrok secrets in.
- **No docker-in-docker.** The gate never builds the server image or brings up the
  tunnel; those remain human steps in `REVIEW.md`.

---

## 1. Golden rules (anti-cheat — violating any fails the run)

1. **Never weaken a test to dodge a failure.** You may *update* a test when a chunk
   in `PLAN.md` **explicitly** requires it (e.g. repointing the auth tests at the
   new `build_server` factory, or `test_server_widget.py` from `app.mcp` to
   `build_server(None)`) — but the replacement assertion must be **at least as
   strict** as the one it replaces. Weakening, deleting, skipping, or `xfail`-ing a
   test to get green is a failed run. If a test seems wrong and no chunk authorises
   the change, stop and record it in `BLOCKERS.md`.
2. **Never weaken tooling config.** `ruff`, `mypy --strict`, and the coverage floor
   (`--cov-fail-under=90`) are fixed. Do not edit `pyproject.toml` lint/type/coverage
   settings to get green.
3. **Never make a live network call in the test path.** All HTTP — the IdP's JWKS,
   token verification — is mocked (`respx`) or driven by a local in-test keypair.
   The live OAuth login stays behind `RUN_LIVE=1` and is **never run by you**.
4. **Never commit secrets.** Only `.env.example` with placeholders. Test keypairs
   are generated at test time, never written to the repo.
5. **Never change the MCP surface or tool behaviour to make a gate pass.** This is a
   refactor: the 11 tools + widget resource, their names, descriptions, and return
   shapes are the **parity contract** (`PLAN.md` §2). If preserving behaviour seems
   to require a surface change, that is a blocker, not a licence.
6. **Verify the one external contract against the installed SDK, not memory.** The
   only thing phase 3 must re-confirm is that `FastMCP`'s public `auth=` /
   `token_verifier=` constructor params and `server.tool()(fn)` registration behave
   as `PLAN.md` assumes — done in Chunk 0 against `mcp==1.27.2`. The broader
   contracts (Apps SDK widget, OAuth metadata) are already verified in
   `Phase2_RESEARCH.md`; consult it rather than re-deriving.

If following the plan honestly means a gate cannot pass, that is a blocker to
report — not a rule to bend.

---

## 2. Do not break what exists — parity is the floor

Phases 1–2 shipped green at 100% coverage. That is the floor you protect, and for a
refactor the bar is higher: **external behaviour must not change at all.**

- **`core` stays MCP-free.** No MCP/FastMCP/OAuth/HTTP import outside `server/`.
- **`server/auth.py` verification logic is unchanged** — `AuthConfig`,
  `load_auth_config`, and `IdpTokenVerifier.verify_token` are reused as-is. Phase 3
  changes only *how the verifier is attached* (constructor injection), never *how a
  token is verified*.
- **The services layer is unchanged** (`_Services`, `_build_services`,
  `_get_services`).
- **Touch only what a chunk names.** No drive-by refactors beyond the named move.
- **Re-run the full gate before and after each chunk.** A chunk starts green and
  ends green. Never commit a red gate.

---

## 3. The loop

The loop is driven by the **shell**, not an in-session `/loop`: each chunk runs as
its own fresh `claude -p` **process**, starting from a clean context and re-reading
this file + `PLAN.md` from cold. One process builds exactly one chunk and exits;
the shell starts the next. State crosses the chunk boundary only through git
commits and `BLOCKERS.md` — never through conversation memory. (Same machinery as
phase 2; the loop script must be pointed at branch `refactor/auth`, a
`phase3-base` tag at the pre-chunk-0 commit, and final chunk **2**.)

For each chunk: (1) read its goal/deliverables/gate in `PLAN.md`; (2) implement only
what it specifies — pull nothing forward; (3) run the full gate (§4); (4) green →
one Conventional Commit → next chunk; (5) red → fix and re-run. After **3 honest
failed attempts**, stop, write `BLOCKERS.md` (chunk number, what you tried, the
exact failing command + output, best hypothesis), leave the repo on the last green
commit, end the run.

---

## 4. The gate (identical for every chunk)

From the repo root, inside the container:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

All four must exit 0. Coverage stays **≥ 90%** (hold 100%). Because the auth wiring
moves *out* from under the `# pragma: no cover` in `main()`, coverage honesty must
**improve**: `build_server`'s auth **and** no-auth branches must both be exercised,
leaving only the genuinely un-runnable `run()` tail behind the pragma. The live
OAuth login and the in-ChatGPT widget render are **out** of the gate — human checks
in `REVIEW.md`.

---

## 5. Dependencies

Managed with `uv`, every dependency pinned (`==`), `uv.lock` committed and matching
`pyproject.toml`. **Phase 3 adds no dependencies.** Anything that seems to need one
→ record in `BLOCKERS.md` and stop.

---

## 6. External contracts

Phase 3 introduces **no new external contracts**. The verified Apps SDK / OAuth /
Python-SDK contracts live in `build_artifacts/Phase 2/Phase2_RESEARCH.md` — treat
it as the reference. The single thing to re-verify is the public-constructor /
registration behaviour of the installed `mcp` (Chunk 0). If the installed SDK
contradicts what `PLAN.md` assumes, stop, record it in `BLOCKERS.md`.

---

## 7. Commits & branch

- Work on **`refactor/auth`**, branched off `main`. Never commit to `main`. Never
  force-push.
- One commit per passed chunk, Conventional Commits, referencing the chunk, e.g.
  `refactor(server): build_server factory + constructor-injected auth  [chunk 1]`.
- Working tree clean (gate green) before each commit.

---

## 8. Code standards (unchanged from phases 1–2)

Python 3.12, `src/` layout, full type annotations, `mypy --strict` with no
unjustified ignores, Google-style docstrings on every public surface, small
single-purpose files (~200-line soft cap), typed errors from `core/errors.py`
(never bare `Exception`), Pydantic v2 for boundary data, no `print` (use
`logging`), comments explain *why*.

---

## 9. Definition of done

Every chunk 0 → 2 committed green. The parity contract (`PLAN.md` §2) holds:
identical MCP surface, stdio still boots unauthenticated, HTTP still rejects with
`401`. No private-attribute auth write remains (`grep -n "_token_verifier" src` is
clean); the `# pragma: no cover` region is just the `run()` tail. After Chunk 2,
refresh `REVIEW.md` with what a human must verify by eye — the **live OAuth login**
and the **widget render in ChatGPT** — then stop. Do not declare the build
"finished and verified": those cannot be confirmed by automated tests alone.
