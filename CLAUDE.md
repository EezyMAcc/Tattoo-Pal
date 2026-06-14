# CLAUDE.md — Phase 2 governance

Operating rules for the **second** autonomous `/loop` build: turning the working
stdio MCP server into a remote, OAuth-protected, ChatGPT-renderable MCP app.
Read this fully before touching code. These rules are non-negotiable and override
any instinct to "just make the gate pass."

This is the governing doc the harness loads. *What* to build lives in `PLAN.md`;
the verified external contracts live in `RESEARCH.md`; the human checklist is
`REVIEW.md` — all at the repo root. This file governs *how* you work.

---

## Supersession — this file governs; the phase-1 docs are archived

The phase-1 governance documents have been moved to `build_artifacts/` and
renamed `Phase1_CLAUDE.md`, `Phase1_PLAN.md`, `Phase1_REVIEW.md`. They are the
**historical record of build 1** — kept as artifacts; do not move, edit, delete,
or follow them.

This root `CLAUDE.md` (with the root `PLAN.md` / `RESEARCH.md` / `REVIEW.md`) is
now the phase-2 governance, and is what the harness loads. Where any phase-1
artifact conflicts with these, **these win.** Specifically:

- **Overridden:** the phase-1 non-goals "no GUI / web front-end" and the implicit
  stdio-only / no-HTTP stance — phase 2 deliberately adds an HTTP transport and a
  ChatGPT Apps SDK **widget** (see `RESEARCH.md` §1). The branch is
  **`feat/remote-app`**, not `feat/auto-build`. The plan is the root `PLAN.md`,
  not `build_artifacts/Phase1_PLAN.md`.
- **Still in force (restated in §1):** every phase-1 anti-cheat rule — never
  weaken tests or tooling, never make a live network call in tests, never commit
  secrets, never touch `main`.

The `/loop` launch prompt should name the root `CLAUDE.md` / `PLAN.md` as
governing and the `build_artifacts/Phase1_*` docs as superseded artifacts.

---

## Where the build runs — inside the dev container

The loop and the gate run **inside the phase-1 dev image** (`tattoo-feed-dev`,
built from the root `Dockerfile`), exactly as phase 1 did — it bundles git, Node,
`uv`, and Claude Code, with **only this project mounted** at `/workspace`.

- Start it with `./run-loop.sh` (mounts `$PWD` → `/workspace`, nothing else on the
  host), or a persistent container you `docker exec` into. Anything written under
  `/workspace` lands back in this folder on the host.
- The full gate (§4) runs in this container.
- **No production secrets enter the build container.** The test suite is hermetic
  (§1.3); the loop needs no Instagram or identity-provider credentials — only
  Claude Code's own auth. Do not pass `IG_*`, IdP, or ngrok secrets in.
- **No docker-in-docker.** Chunk 4 *writes* `Dockerfile.server` and
  `docker-compose.yml` but must **not** build or run them inside the loop
  container — the gate is hermetic and never builds images. Building the server
  image and bringing up the tunnel is a **human step in `REVIEW.md`**.

---

## 1. Golden rules (anti-cheat — violating any fails the run)

1. **Never weaken a test to dodge a failure.** You may *update* a test when a
   chunk in `PLAN.md` **explicitly** changes a contract (e.g. `next_inspiration`
   moves from an image content block to a widget result) — but the replacement
   assertion must be **at least as strict** as the one it replaces, and the
   change must be the one the chunk specifies. Weakening, deleting, skipping, or
   `xfail`-ing a test to get green is a failed run. If a test seems wrong and no
   chunk authorises changing it, stop and record it in `BLOCKERS.md`.
2. **Never weaken tooling config** to pass a gate. `ruff`, `mypy --strict`, and
   the coverage floor (`--cov-fail-under=90`) are fixed. Do not edit
   `pyproject.toml` lint/type/coverage settings to get green.
3. **Never make a live network call in the test path.** All HTTP — Instagram, the
   identity provider's JWKS, token introspection — is mocked (`respx`) or driven
   by local fixtures (a test keypair generated in the test). The live integration
   test and any real OAuth login stay behind `RUN_LIVE=1` and are **never run by
   you**.
4. **Never commit secrets.** No tokens, client secrets, JWKS private keys, or
   `.env`. Only `.env.example` with placeholders is committed. Test keypairs are
   generated at test time, never written to the repo.
5. **Never present an unauthenticated endpoint as the finished state.** Phase 2's
   point is auth. HTTP without the auth chunk behind it is intermediate, never
   "done."
6. **Verify external contracts against `RESEARCH.md` and its live links before
   implementing.** The Apps SDK widget shape, the MCP OAuth metadata paths, and
   the Python SDK auth API must be confirmed against current docs at build time.
   Do not code an API shape from memory; if the live docs contradict
   `RESEARCH.md`, stop, update `RESEARCH.md`, and note it in `BLOCKERS.md`.

If following the plan honestly means a gate cannot pass, that is a blocker to
report — not a rule to bend.

---

## 2. Do not break what exists

Phase 1 shipped 100% green at 100% coverage. That is the floor you protect.

- **`core` stays MCP-free.** No chunk may add an MCP, FastMCP, OAuth, or HTTP
  import under `src/tattoo_feed/` *except* inside `server/`. The two-layer split
  is the whole reason a future GUI is cheap; do not erode it.
- **Touch only what a chunk names.** No drive-by refactors.
- **Re-run the full gate before and after each chunk.** A chunk starts from green
  and ends on green. Never commit a red gate.

---

## 3. The loop

Work one chunk at a time, in order. For each chunk:

1. Read its goal, deliverables, and success gate in `PLAN.md`.
2. Re-verify any external contract it touches against `RESEARCH.md`'s live links.
3. Implement only what the chunk specifies. No pulling work forward.
4. Run the full gate (§4).
5. Green → one Conventional Commit for the chunk → next chunk.
6. Red → fix and re-run. After **3 honest failed attempts**, stop, write
   `BLOCKERS.md` (chunk number, what you tried, exact failing command + output,
   best hypothesis), leave the repo on the last green commit, end the run.

Never start a chunk before the previous chunk's gate is green and committed.

---

## 4. The gate (identical for every chunk)

Run from the repo root, inside the container:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

All four must exit 0. New hermetic tests added by a chunk are part of the gate
from that chunk on. The widget's *visual* behaviour and the *live* OAuth login
are explicitly **out** of the gate — they are human checks in `REVIEW.md`. Keep
non-testable surface (the widget JS, the stdio/http entrypoint) thin and behind
the one permitted `# pragma: no cover` (`main()` in `server/app.py`), so coverage
stays honest without pragma-spam.

---

## 5. Dependencies

- Managed with `uv`, every dependency pinned exactly (`==`), `uv.lock` committed
  and matching `pyproject.toml`.
- Phase 2 may need new **direct** dependencies. The approved phase-2 additions are
  listed in `PLAN.md` §"Approved dependencies". Anything not on that list: record
  the need in `BLOCKERS.md` and stop. No incidental packages.
- If a pin must change (e.g. bumping `mcp` for the auth/widget API), do it in the
  chunk that needs it, update `uv.lock`, and state the old→new version in the
  commit body.

---

## 6. Commits & branch

- Work on **`feat/remote-app`**, branched off the current tip. Never commit to
  `main`. Never force-push.
- One commit per passed chunk, Conventional Commits, referencing the chunk, e.g.
  `feat(server): OAuth2.1 resource-server token verification  [chunk 2]`.
- Working tree clean (gate green) before each commit.

---

## 7. Code standards (unchanged from phase 1)

Python 3.12, `src/` layout, full type annotations, `mypy --strict` with no
unjustified ignores, Google-style docstrings on every public surface, small
single-purpose files (~200-line soft cap), typed errors from `core/errors.py`
(never bare `Exception`), Pydantic v2 for boundary data, no `print` (use
`logging`), comments explain *why*. New typed errors needed for auth go in
`core/errors.py` and extend `TattooFeedError`.

---

## 8. Secrets & hosting hygiene

- The running server reads all credentials from the environment: Instagram
  (`IG_ACCESS_TOKEN`, `IG_USER_ID`), the data dir (`TATTOO_FEED_DATA_DIR`), and
  the identity-provider settings (issuer, audience, JWKS URL). None baked into the
  image or committed.
- ngrok is **plain TLS ingress only** — no auth logic in ngrok; auth is in the
  server. The ngrok authtoken is an env var, never committed.
- The public endpoint must reject unauthenticated requests with `401` before any
  tool runs. Asserted by a hermetic test in Chunk 2.

---

## 9. Definition of done

Every chunk 0 → 5 committed green. After Chunk 5, refresh `REVIEW.md`
with exactly what a human must verify by eye — the image rendering **in ChatGPT
via the widget**, the **real OAuth login**, and the **live tunnel** — plus the
steps to run it. Then stop. Do not declare the build "finished and verified":
neither the visual render nor the live auth flow can be confirmed by automated
tests alone.
