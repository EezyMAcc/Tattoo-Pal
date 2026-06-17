# BUILD.md — Phase 2 build governance (index)

The index for the **second** autonomous `/loop` build of tattoo-feed: turning the
working stdio MCP server into a **remotely hosted, OAuth-protected,
ChatGPT-renderable** MCP app. The phase-2 governance docs live at the repo root
(this file points into them); the phase-1 docs are archived under
`build_artifacts/`.

Read these in order (all at the repo root):

1. **`CLAUDE.md`** — *how* you work, and **the governing doc for this build**.
   Golden rules, the loop, the gate, commit discipline, failure policy, plus the
   supersession statement (phase-1 docs are archived artifacts) and where the
   build runs (the dev container). **Non-negotiable.**
2. **`PLAN.md`** — *what* you build. The current-state reconciliation (what
   already exists and how it constrains the work) followed by the chunked build
   (Chunk 0 → Chunk 5), each with a success gate.
3. **`RESEARCH.md`** — the *verified, current* documentation the build depends
   on (Apps SDK widget contract, MCP OAuth spec, the Python SDK auth API, ngrok,
   ChatGPT connector). Every external-contract decision in `PLAN.md` traces back
   to a source here. **Re-verify against the live links before coding a chunk —
   do not implement an external API shape from memory.**
4. **`REVIEW.md`** — the human verification checklist to run *after* the build
   (the things automated gates cannot confirm: image actually rendering in
   ChatGPT, the real OAuth login, the live tunnel).

## Governance — which docs are in force

The root `CLAUDE.md` governs phase 2 and is what the harness loads. The phase-1
`CLAUDE.md`, `PLAN.md`, and `REVIEW.md` have been moved to `build_artifacts/` and
renamed `Phase1_*.md` — kept **unchanged as build-1 artifacts** and
**superseded** for this work (see the root `CLAUDE.md` "Supersession" section).

## What this build is NOT

It does not rewrite the phase-1 `core`. The two-layer split held; `core` stays
untouched except where a chunk explicitly says so. The work lives almost
entirely in `server/`, deployment files, and docs.

## How to run it

The loop runs **inside the `tattoo-feed-dev` container** (root `Dockerfile`) and
is driven by the **shell** — `build-loop.sh` — one chunk per fresh `claude`
process. This is deliberate: each chunk must start from a clean context window so
it re-reads `CLAUDE.md` / `PLAN.md` / `RESEARCH.md` and re-verifies external
contracts from cold. An in-session `/loop` keeps a single growing context across
all chunks and does **not** give that fresh boundary — do not use it for this.

Set up the Claude token, then launch unattended (see
`build_artifacts/Phase 2/PROMPTS.md` for the token steps):

```bash
./run-loop.sh --build          # runs build-loop.sh in the container, headless
```

`build-loop.sh` detects the next chunk from git (`phase2-base..HEAD`), runs one
`claude -p` per chunk with a single-chunk prompt, and stops when chunk 5 is
committed or a `BLOCKERS.md` appears. Each chunk's transcript is saved to
`build_artifacts/*.txt` (gitignored). State passes between chunks only through
git commits — never conversation memory.

The build container needs **no** Instagram / IdP / ngrok secrets — the tests are
hermetic. Chunk 4 *writes* `Dockerfile.server` + `docker-compose.yml` but does
not build or run them (no docker-in-docker); that, and the live verification, are
human steps in `REVIEW.md`.

After Chunk 5, stop. Image rendering in ChatGPT and the OAuth login are
**human-verified** (see `REVIEW.md`); do not declare the build "verified".
