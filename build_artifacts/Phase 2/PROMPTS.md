# PROMPTS.md — how to launch the phase-2 loop

**Scaffolding, not governance.** This file only tells you how to *launch* the
build (token + container + the command). Nothing in `CLAUDE.md` / `PLAN.md` /
`RESEARCH.md` references it — they govern *what* and *how* you build.

The loop is driven by the **shell** (`build-loop.sh`): each chunk runs as its own
fresh `claude` process (clean context per chunk), launched via
`./run-loop.sh --build`. There is no `/loop` prompt to paste — an in-session
`/loop` keeps one growing context across all chunks and is exactly what this
mechanism replaces.

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
   `run-loop.sh` forwards it in — this avoids the broken in-container browser
   login, and the ephemeral container would not persist a login anyway.

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
   ./run-loop.sh                                          # interactive shell in the container
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

## Launch — full autonomous build (Chunk 0 → 5)

From the **same shell** you exported the token in, run the loop unattended:

```bash
./run-loop.sh --build
# or, to also keep one combined host-side log (outside the repo so it does not
# dirty the worktree the loop builds in):
./run-loop.sh --build 2>&1 | tee ~/phase2-build.log
```

That's the whole launch. `run-loop.sh --build` starts the container headless and
runs `build-loop.sh`, which:

- detects the next chunk from git (`phase2-base..HEAD`) — highest committed
  `[chunk N]` → builds `N+1`; none → starts at chunk 0;
- runs **one fresh `claude -p` process per chunk** with a single-chunk prompt
  (the prompt lives in `build-loop.sh`), so each chunk re-reads `CLAUDE.md` /
  `PLAN.md` / `RESEARCH.md` from a clean context and re-verifies external
  contracts;
- on a green gate, the chunk makes one Conventional Commit on `feat/remote-app`
  and the process exits; the shell then spawns the next;
- stops when `[chunk 5]` is committed, when a `BLOCKERS.md` appears, or if a
  process makes no commit (the no-progress guard).

Each chunk's transcript is saved to `build_artifacts/*.txt` (gitignored).

**Full autonomy — nothing to toggle.** Unlike an interactive session (where you'd
shift-tab to auto/bypass mode), the loop runs each chunk with
`claude -p --dangerously-skip-permissions`, so no permission prompt ever blocks
it. `build-loop.sh` also exports `IS_SANDBOX=1`, which is required for that flag
to work as **root** (the container's user) — without it Claude refuses and the
run would stop on chunk 0. Both are already wired in; just run the command above.

> Precondition: the `phase2-base` tag must point at the pre-chunk-0 commit and
> `feat/remote-app` must be checked out — `build-loop.sh` refuses to run
> otherwise. (Both are already set up.)

---

## Manual pacing (one chunk, by hand)

To drive a single chunk yourself instead of the loop — e.g. to inspect after a
blocker — drop into the container (`./run-loop.sh`) and run one iteration's worth
by hand, or run `claude` interactively and instruct it to build only the next
chunk per `CLAUDE.md` / `PLAN.md`, then stop. Do not use an in-session `/loop`:
it will not give the fresh-context-per-chunk boundary the build relies on.

---

## If it stops early

A `BLOCKERS.md` means a chunk failed its gate 3 times (or hit an external-contract
mismatch). Read it — it names the chunk, what was tried, the failing
command/output, and a hypothesis. The repo is left on the last green commit, so
you can fix the blocker and re-run `./run-loop.sh --build` to resume from there
(the loop re-detects the next chunk from git).
