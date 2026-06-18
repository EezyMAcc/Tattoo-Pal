#!/usr/bin/env bash
#
# phase3_build-loop.sh — drive the phase-3 build (the auth-wiring refactor),
# ONE chunk per fresh `claude` process.
#
# Run this INSIDE the tattoo-feed-dev container, from /workspace:
#     ./phase3_build-loop.sh
# or, unattended from the host (it launches the container for you):
#     ./phase3_run-loop.sh --build
#
# WHY A SHELL LOOP (and not an in-session `/loop`):
#   Each chunk must start from a CLEAN context window, so it re-reads the
#   governance (CLAUDE.md / PLAN.md) and re-verifies the one external contract
#   from cold — exactly the discipline the governing docs demand. A `/loop`
#   running inside one `claude` session keeps a single, ever-growing context
#   across every chunk (summarised as it fills); that is the failure this script
#   exists to fix. Here the loop boundary lives in the SHELL: each iteration
#   spawns a brand-new `claude -p` PROCESS = a brand-new context. State crosses
#   the chunk boundary only through git commits and BLOCKERS.md — never through
#   conversation memory.
#
# WHAT IT DOES NOT DO:
#   It never builds or runs the server image / tunnel (no docker-in-docker), and
#   it passes no Instagram / IdP / ngrok secrets in. The phase-3 gate is
#   hermetic. See CLAUDE.md "Where the build runs".
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

readonly BRANCH="refactor/auth"
readonly BASE_REF="phase3-base"   # tag at the pre-chunk-0 commit; anchors detection
readonly FINAL_CHUNK=2
readonly MAX_ITERS=5              # 3 chunks (0..2) + slack; hard backstop against runaway loops
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

# Highest phase-3 chunk number committed in BASE_REF..HEAD, or -1 if none.
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
You are continuing an autonomous, chunked build of tattoo-feed PHASE 3 — a
behaviour-preserving refactor that removes the module-level FastMCP global and
moves OAuth onto the SDK's public constructor parameters. This invocation is a
SINGLE fresh context window and must build EXACTLY ONE chunk: chunk ${next}. Then
exit. Do not start any later chunk — a separate process does that next.

Governance:
- The repo-root CLAUDE.md is the governing doc (how you work) and PLAN.md is what
  you build. Read BOTH IN FULL before writing code. The motivation and success
  criteria live in scratchpads/phase-3-motivation.md, with the decision detail in
  scratchpads/removing-the-global.md and the problem anatomy in
  scratchpads/auth-wiring-seam.md.
- Phases 1 and 2 are ARCHIVED under build_artifacts/ (Phase1_* and Phase2_*).
  They are the historical record — do not move, edit, delete, or follow them.
  Where any archived doc conflicts with the root CLAUDE.md / PLAN.md, the root
  docs win.

Before you start chunk ${next}:
1. Run: git log --oneline ${BASE_REF}..HEAD
   Confirm the highest committed phase-3 chunk is exactly $((next - 1)) (or that
   there are none, if ${next} is 0). If git disagrees with "build chunk ${next}",
   STOP and write BLOCKERS.md explaining the mismatch — do not guess.
2. Confirm the working tree is clean and the previous chunk's gate is green.
3. Phase 3 introduces NO new external contracts (CLAUDE.md section 6). The verified
   Apps SDK / OAuth / Python-SDK contracts already live in
   build_artifacts/Phase 2/Phase2_RESEARCH.md — consult it, do not re-derive. The
   ONLY thing to (re)confirm is, in chunk 0, that the installed mcp (1.27.2) public
   constructor accepts auth= / token_verifier= and validates the pair, and that
   server.tool()(fn) / server.resource(...) registration behaves as PLAN.md
   assumes — verified against the INSTALLED SDK, not from memory, and captured in
   PHASE3_RECONCILIATION.md. If the installed SDK contradicts what PLAN.md assumes,
   STOP and record it in BLOCKERS.md.

Build chunk ${next}:
- Implement ONLY what chunk ${next} in PLAN.md specifies. Pull nothing forward.
- Run the full gate (CLAUDE.md section 4 — ruff format --check, ruff check,
  mypy --strict src, pytest with --cov-fail-under=90). All four must exit 0.
  Coverage stays >= 90% (hold 100%); because the auth wiring moves out from under
  the # pragma: no cover in main(), build_server's auth AND no-auth branches must
  both be exercised.
- On green: make ONE Conventional Commit for the chunk on ${BRANCH}, with the
  chunk tag in the subject, e.g.
  "refactor(server): build_server factory + constructor-injected auth  [chunk ${next}]".
  Then EXIT.
- If the gate cannot pass after 3 honest attempts: STOP. Write BLOCKERS.md (chunk
  number, what you tried, the exact failing command and its output, best
  hypothesis). Leave the repo on the last green commit. Exit.

Hard rules (violating any fails the run):
- This is a REFACTOR. Never change the MCP surface or tool behaviour to make a
  gate pass: the 11 tools + widget resource, their names, descriptions, and return
  shapes are the parity contract (PLAN.md section 2). If preserving behaviour seems
  to require a surface change, that is a blocker, not a licence.
- Never weaken a test or tooling config to get green. You may UPDATE a test only
  when chunk ${next} explicitly requires it (e.g. repointing the auth tests at the
  real build_server factory, or test_server_widget.py from app.mcp to
  build_server(None)), and the replacement assertion must be at least as strict as
  the one it replaces.
- core stays MCP-free; server/auth.py verification logic (AuthConfig,
  load_auth_config, IdpTokenVerifier.verify_token) and the services layer are
  reused UNCHANGED. Phase 3 changes only HOW the verifier is attached.
- No private-attribute auth write may remain: auth is configured only through the
  public constructor params. (grep -n "_token_verifier" src must be clean by the
  end of chunk 1.)
- Never make a live network call in the test path — all HTTP is mocked (respx) or
  driven by a local in-test keypair. RUN_LIVE stays unset.
- Never commit secrets. Only .env.example with placeholders.
- Phase 3 adds NO dependencies. Anything that seems to need one -> BLOCKERS.md and
  stop.
- Never touch main. Never force-push.

If chunk ${next} is the final chunk (${FINAL_CHUNK}): after committing it, refresh
REVIEW.md with what a human must verify by eye — the LIVE OAuth login and the
WIDGET render in ChatGPT — plus how to confirm parity (tool set unchanged; stdio
still boots; curl .../mcp -> 401), mark scratchpads/auth-wiring-seam.md resolved,
and fix scratchpads/phase-3-motivation.md's "branch name TBD" -> refactor/auth, as
PLAN.md chunk 2 specifies. Commit that. Do NOT declare the build verified — the
live OAuth login and the in-ChatGPT widget render need human eyes.
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
  # this folder and receives only the Claude token (see phase3_run-loop.sh).
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
