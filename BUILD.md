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

Run the loop **inside the `tattoo-feed-dev` container** (root `Dockerfile` /
`./run-loop.sh`), one chunk at a time, same discipline as phase 1. Launch prompt:

> Build phase 2 by following the root `PLAN.md` exactly, governed by the root
> `CLAUDE.md`. The `build_artifacts/Phase1_*.md` docs are superseded phase-1
> artifacts — do not follow them. Work ONE chunk at a time (0 → 5) inside the
> container. Run the full gate after each; commit on green to `feat/remote-app`;
> stop and write `BLOCKERS.md` after 3 failed honest attempts on a chunk. Verify
> external API shapes against the root `RESEARCH.md` and its live links before
> implementing — never from memory.

The build container needs **no** Instagram / IdP / ngrok secrets — the tests are
hermetic. Chunk 4 *writes* `Dockerfile.server` + `docker-compose.yml` but does
not build or run them (no docker-in-docker); that, and the live verification, are
human steps in `REVIEW.md`.

After Chunk 5, stop. Image rendering in ChatGPT and the OAuth login are
**human-verified** (see `REVIEW.md`); do not declare the build "verified".
