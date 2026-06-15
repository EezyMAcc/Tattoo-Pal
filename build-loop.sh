#!/usr/bin/env bash
#
# build-loop.sh — drive the phase-2 build, ONE chunk per fresh `claude` process.
#
# Run this INSIDE the tattoo-feed-dev container, from /workspace:
#     ./build-loop.sh
# or, unattended from the host (it launches the container for you):
#     ./run-loop.sh --build
#
# WHY A SHELL LOOP (and not an in-session `/loop`):
#   Each chunk must start from a CLEAN context window, so it re-reads the
#   governance (CLAUDE.md / PLAN.md / RESEARCH.md) and re-verifies external
#   contracts from cold — exactly the discipline the governing docs demand.
#   A `/loop` running inside one `claude` session keeps a single, ever-growing
#   context across every chunk (summarised as it fills); that is the failure
#   this script exists to fix. Here the loop boundary lives in the SHELL: each
#   iteration spawns a brand-new `claude -p` PROCESS = a brand-new context.
#   State crosses the chunk boundary only through git commits and BLOCKERS.md —
#   never through conversation memory.
#
# WHAT IT DOES NOT DO:
#   It never builds or runs the server image / tunnel (no docker-in-docker), and
#   it passes no Instagram / IdP / ngrok secrets in. The gate is hermetic. See
#   CLAUDE.md "Where the build runs".

set -euo pipefail

# Run from the repo root regardless of where invoked.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Full autonomy: `claude -p ... --dangerously-skip-permissions` is the headless
# equivalent of interactively toggling auto/bypass mode — it answers every tool
# permission prompt itself so the run never blocks. But Claude Code REFUSES
# --dangerously-skip-permissions when running as root ("skip-permissions cannot
# be used with root"), and the dev container runs as root. IS_SANDBOX=1 is the
# supported override: it declares "this is a sandbox, allow it". That is honest
# here — the ephemeral, single-folder-mount container IS the real isolation
# boundary, not Claude's in-process check. Without this the loop dies on chunk 0.
export IS_SANDBOX=1

readonly BRANCH="feat/remote-app"
readonly BASE_REF="phase2-base"   # tag at the pre-chunk-0 commit; anchors detection
readonly FINAL_CHUNK=5
readonly MAX_ITERS=8              # 6 chunks + slack; hard backstop against runaway loops
readonly LOG_DIR="build_artifacts" # build_artifacts/*.txt is gitignored -> tree stays clean

# --- pre-flight guards -------------------------------------------------------
command -v claude >/dev/null 2>&1 || { echo "error: 'claude' not on PATH (run inside the dev container)." >&2; exit 2; }
command -v git    >/dev/null 2>&1 || { echo "error: 'git' not on PATH." >&2; exit 2; }

git rev-parse --verify --quiet "refs/tags/${BASE_REF}" >/dev/null \
  || { echo "error: tag '${BASE_REF}' not found. It must point at the pre-chunk-0 commit." >&2; exit 2; }

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$BRANCH" ]; then
  echo "error: on branch '$current_branch', expected '$BRANCH'. Checkout it first." >&2
  exit 2
fi

# Highest phase-2 chunk number committed in BASE_REF..HEAD, or -1 if none.
highest_chunk() {
  git log --oneline "${BASE_REF}..HEAD" \
    | grep -oE '\[chunk [0-9]+\]' \
    | grep -oE '[0-9]+' \
    | sort -n | tail -1 || true
}

# --- the single-chunk prompt (rebuilt each iteration with the chunk number) --
# Unquoted heredoc so ${next}/${FINAL_CHUNK} expand. No backticks/`$()` inside.
chunk_prompt() {
  local next="$1"
  cat <<PROMPT
You are continuing an autonomous, chunked build of tattoo-feed phase 2. This
invocation is a SINGLE fresh context window and must build EXACTLY ONE chunk:
chunk ${next}. Then exit. Do not start any later chunk — a separate process does
that next.

Governance:
- The repo-root CLAUDE.md is the governing doc (how you work) and PLAN.md is what
  you build. Read CLAUDE.md, PLAN.md and RESEARCH.md IN FULL before writing code.
- The docs under build_artifacts (the "Phase 1" folder / Phase1_*.md) are
  superseded phase-1 artifacts. Do not follow them.

Before you start chunk ${next}:
1. Run: git log --oneline ${BASE_REF}..HEAD
   Confirm the highest committed phase-2 chunk is exactly $((next - 1)) (or that
   there are none, if ${next} is 0). If git disagrees with "build chunk ${next}",
   STOP and write BLOCKERS.md explaining the mismatch — do not guess.
2. Confirm the working tree is clean and the previous chunk's gate is green.
3. Re-verify any external API shape this chunk touches (Apps SDK widget, MCP
   OAuth metadata, the Python SDK auth API, ngrok) against RESEARCH.md and its
   live links — never from memory. If the live docs contradict RESEARCH.md, STOP,
   update RESEARCH.md, and note it in BLOCKERS.md.

Build chunk ${next}:
- Implement ONLY what chunk ${next} in PLAN.md specifies. Pull nothing forward.
- Run the full gate (CLAUDE.md section 4 — ruff format --check, ruff check,
  mypy --strict src, pytest with --cov-fail-under=90). All four must exit 0.
- On green: make ONE Conventional Commit for the chunk on ${BRANCH}, with the
  chunk tag in the subject, e.g. "feat(server): ...  [chunk ${next}]". Then EXIT.
- If the gate cannot pass after 3 honest attempts: STOP. Write BLOCKERS.md (chunk
  number, what you tried, the exact failing command and its output, best
  hypothesis). Leave the repo on the last green commit. Exit.

Hard rules (violating any fails the run):
- Never weaken a test or tooling config to get green. You may UPDATE a test only
  when chunk ${next} explicitly changes a contract, and the replacement assertion
  must be at least as strict as the one it replaces.
- Never make a live network call in the test path — all HTTP is mocked (respx) or
  driven by local fixtures. RUN_LIVE stays unset.
- Never commit secrets. Only .env.example with placeholders.
- Never touch main. Never force-push.

If chunk ${next} is the final chunk (${FINAL_CHUNK}): after committing it, fill in
ONLY REVIEW.md's two bracketed sections (chunks completed; anything flagged for
the human), commit that, and stop. Do NOT declare the build verified — image
rendering in ChatGPT and the live OAuth login need human eyes.
PROMPT
}

# --- the loop ----------------------------------------------------------------
echo "build-loop: branch=${BRANCH} base=${BASE_REF} final=chunk ${FINAL_CHUNK} max_iters=${MAX_ITERS}"

for ((i = 1; i <= MAX_ITERS; i++)); do
  hi="$(highest_chunk)"; hi="${hi:--1}"

  if [ "$hi" -ge "$FINAL_CHUNK" ]; then
    echo "build-loop: all chunks 0..${FINAL_CHUNK} committed. Done."
    echo "build-loop: next steps are the human checks in REVIEW.md."
    exit 0
  fi

  if [ -f BLOCKERS.md ]; then
    echo "build-loop: BLOCKERS.md present — a chunk could not pass its gate. Stopping." >&2
    exit 1
  fi

  next=$((hi + 1))
  log="${LOG_DIR}/loop-chunk-$(printf '%02d' "$next")-$(date +%Y%m%d-%H%M%S).txt"
  echo "=== build-loop iteration ${i}/${MAX_ITERS}: building chunk ${next} (log: ${log}) ==="

  before="$(git rev-parse HEAD)"

  # One fresh context window. --dangerously-skip-permissions runs every tool
  # without prompting (full autonomy); IS_SANDBOX=1 (exported above) lets it do
  # so as root inside the container. Acceptable here: the container mounts only
  # this folder and receives only the Claude token (see run-loop.sh).
  set +e
  claude -p "$(chunk_prompt "$next")" --dangerously-skip-permissions 2>&1 | tee "$log"
  claude_status=${PIPESTATUS[0]}
  set -e
  [ "$claude_status" -eq 0 ] || echo "build-loop: claude exited ${claude_status} on chunk ${next}." >&2

  after="$(git rev-parse HEAD)"
  if [ "$before" = "$after" ] && [ ! -f BLOCKERS.md ]; then
    echo "build-loop: no new commit and no BLOCKERS.md after chunk ${next} — stopping to avoid a spin." >&2
    echo "build-loop: inspect ${log} to see why the chunk did not commit." >&2
    exit 1
  fi
done

echo "build-loop: reached MAX_ITERS=${MAX_ITERS} without completing — stopping." >&2
exit 1
