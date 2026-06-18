# phase3_LOOPSTART.md — how to launch the phase-3 loop

**Scaffolding, not governance.** This file only tells you how to *launch* the
phase-3 build (the auth-wiring refactor) — token + container + the command.
Nothing in `CLAUDE.md` / `PLAN.md` references it; those govern *what* and *how*
you build. The motivation lives in `scratchpads/phase-3-motivation.md`.

The loop is driven by the **shell** (`phase3_build-loop.sh`): each chunk runs as
its own fresh `claude` process (clean context per chunk), launched via
`./phase3_run-loop.sh --build`. There is no `/loop` prompt to paste — an
in-session `/loop` keeps one growing context across all chunks and is exactly
what this mechanism replaces.

Phase 3 is **3 chunks (0 → 2)**, on branch **`refactor/auth`**, anchored at the
**`phase3-base`** tag. The gate is hermetic — **no** Instagram / IdP / ngrok
secrets, and phase 3 adds **no** dependencies and **no** new external contracts.

---

## Preconditions (already set up — verify, don't redo)

`phase3_build-loop.sh` refuses to run unless both hold. They are already in place;
confirm with the commands shown:

1. **Branch `refactor/auth` is checked out.**
   ```bash
   git rev-parse --abbrev-ref HEAD          # expect: refactor/auth
   ```
2. **The `phase3-base` tag points at the pre-chunk-0 commit** (no `src/` change
   yet, so it is the tip before chunk 0):
   ```bash
   git log -1 --oneline phase3-base         # the governance/scripts commit
   git log --oneline phase3-base..HEAD      # expect: empty (nothing built yet)
   ```
   Empty output means the loop will detect "no chunks committed" and start at
   chunk 0. If it is non-empty, the highest committed `[chunk N]` decides the
   next chunk instead.
3. **Working tree is clean.** Chunk 0 asserts this; a dirty tree means the loop
   builds against uncommitted state.
   ```bash
   git status --short                       # expect: empty
   ```

---

## Setup (on the host, before launching)

1. Build the dev image if you haven't this session (it installs Claude Code and
   pre-seeds its onboarding state so interactive `claude` skips the first-run
   wizard and uses the forwarded token — see `scratchpads/claude-in-docker-sandbox.md`):
   ```bash
   docker build -t tattoo-feed-dev .
   ```
2. Authenticate Claude Code for the container. On the **host** (where your
   Claude Code is already logged in), mint a long-lived token and export it so
   `phase3_run-loop.sh` forwards it in — this avoids the broken in-container
   browser login, and the ephemeral container would not persist a login anyway.

   Capture it the **paste-proof** way — the enemy is terminal line-wrapping
   corrupting the long token on copy/paste. Write it to a temp file, eyeball it,
   then export (run each short line separately so nothing wraps):
   ```bash
   claude setup-token | tee /tmp/st.txt
   grep -oaE 'sk-ant-oat01-[A-Za-z0-9_-]+' /tmp/st.txt | head -1   # confirm it looks whole
   export CLAUDE_CODE_OAUTH_TOKEN="$(grep -oaE 'sk-ant-oat01-[A-Za-z0-9_-]+' /tmp/st.txt | head -1)"
   echo "length: ${#CLAUDE_CODE_OAUTH_TOKEN}"   # expect ~100
   rm -f /tmp/st.txt                            # it held the token — delete it
   ```
   If length is 0/short, the token has a char outside `[A-Za-z0-9_-]`; broaden
   the pattern to `sk-ant-oat01-[!-~]+`.
3. (Recommended) verify the **autonomous path** inside the container before the
   long run — this is the exact mode the loop uses (skip-permissions, as root),
   not just a plain auth check:
   ```bash
   ./phase3_run-loop.sh                                   # interactive shell in the container
   IS_SANDBOX=1 claude -p "say hi" --dangerously-skip-permissions
   exit                                                   # leave the container
   ```
   A normal reply confirms both that the token authenticates **and** that
   skip-permissions is allowed as root — so the unattended run won't stall. A
   root/permission error means the in-container `claude` version uses a different
   override; fix that before launching `--build`.

The build needs **no** Instagram / IdP / ngrok secrets — the tests are hermetic.
The only credential passed in is your Claude Code token (step 2), so `claude` is
logged in without a browser. Don't pass `IG_*`, identity-provider, or ngrok
values in.

---

## Launch — full autonomous build (Chunk 0 → 2)

From the **same shell** you exported the token in, run the loop unattended:

```bash
./phase3_run-loop.sh --build
# or, to also keep one combined host-side log (outside the repo so it does not
# dirty the worktree the loop builds in):
./phase3_run-loop.sh --build 2>&1 | tee ~/phase3-build.log
```

That's the whole launch. `phase3_run-loop.sh --build` starts the container
headless and runs `phase3_build-loop.sh`, which:

- detects the next chunk from git (`phase3-base..HEAD`) — highest committed
  `[chunk N]` → builds `N+1`; none → starts at chunk 0;
- runs **one fresh `claude -p` process per chunk** with a single-chunk prompt
  (the prompt lives in `phase3_build-loop.sh`), so each chunk re-reads `CLAUDE.md`
  / `PLAN.md` from a clean context. Phase 3 has no new external contracts to
  re-verify — chunk 0 confirms only the installed `mcp` (1.27.2) constructor /
  registration behaviour against `PLAN.md` and records it in
  `PHASE3_RECONCILIATION.md`; the broader verified contracts live in
  `build_artifacts/Phase 2/Phase2_RESEARCH.md`;
- on a green gate, the chunk makes one Conventional Commit on `refactor/auth`
  and the process exits; the shell then spawns the next;
- stops when `[chunk 2]` is committed, when a `BLOCKERS.md` appears, or if a
  process makes no commit (the no-progress guard).

Each chunk's transcript is saved to `build_artifacts/*.txt` (gitignored).

**Full autonomy — nothing to toggle.** Unlike an interactive session (where you'd
shift-tab to auto/bypass mode), the loop runs each chunk with
`claude -p --dangerously-skip-permissions`, so no permission prompt ever blocks
it. `phase3_build-loop.sh` also exports `IS_SANDBOX=1`, which is required for that
flag to work as **root** (the container's user) — without it Claude refuses and
the run would stop on chunk 0. Both are already wired in; just run the command
above.

> Precondition recap: the `phase3-base` tag must point at the pre-chunk-0 commit
> and `refactor/auth` must be checked out — `phase3_build-loop.sh` refuses to run
> otherwise. (Both are already set up — see "Preconditions" above.)

---

## Manual pacing (one chunk, by hand)

To drive a single chunk yourself instead of the loop — e.g. to inspect after a
blocker — drop into the container (`./phase3_run-loop.sh`) and run one iteration's
worth by hand, or run `claude` interactively and instruct it to build only the
next chunk per `CLAUDE.md` / `PLAN.md`, then stop. Do not use an in-session
`/loop`: it will not give the fresh-context-per-chunk boundary the build relies
on.

---

## What "done" looks like

The loop exits 0 after `[chunk 2]` is committed. At that point chunks 0–2 are
each a green Conventional Commit on `refactor/auth`, and (per `PLAN.md` §8 /
`CLAUDE.md` §9):

- the parity contract holds — same 11 tools + widget resource, stdio still boots
  unauthenticated, HTTP still rejects with `401`;
- `grep -n "_token_verifier" src` is clean (no private-attribute auth write);
- the `# pragma: no cover` region is just the `run()` tail;
- `REVIEW.md` lists the **human-only** checks that remain.

Those human-only checks — the **live OAuth login** and the **widget render in
ChatGPT** — are **not** confirmed by the loop. Run them by eye per `REVIEW.md`
before declaring phase 3 finished.

---

## If it stops early

A `BLOCKERS.md` means a chunk failed its gate 3 times (or hit an external-contract
mismatch with the installed SDK). Read it — it names the chunk, what was tried,
the failing command/output, and a hypothesis. The repo is left on the last green
commit, so you can fix the blocker and re-run `./phase3_run-loop.sh --build` to
resume from there (the loop re-detects the next chunk from git).
