# PROMPTS.md — launch prompts for the phase-2 loop

**Scaffolding, not governance.** This file exists only to hand you the prompt to
start the build. Delete it once the loop is running (it's untracked and the loop
ignores it, but keeping the repo tidy is the point). Nothing in `CLAUDE.md` /
`PLAN.md` / `RESEARCH.md` references it.

---

## Before you paste the prompt

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
3. Drop into the dev container (mounts only this folder; forwards the token).
   Run this from the **same shell** you exported the token in:
   ```bash
   ./run-loop.sh
   ```
4. Inside the container, sanity-check auth, then start Claude Code and open a
   **fresh chat** (the image's pre-seeded onboarding state means no login
   wizard — it goes straight in using the token):
   ```bash
   claude -p "say hi"   # a normal reply confirms the token authenticates
   claude               # interactive — should start without any sign-in prompt
   ```
5. Delete this file (`rm PROMPTS.md`), then paste the prompt below.

The build needs **no** Instagram / IdP / ngrok secrets — the tests are hermetic.
The only credential passed in is your Claude Code token (step 2), so `claude` is
logged in without a browser. Don't pass `IG_*`, identity-provider, or ngrok
values in.

---

## Primary prompt — full autonomous build (Chunk 0 → 5)

Paste this verbatim:

> /loop Build phase 2 of tattoo-feed by following `PLAN.md` exactly, governed by
> `CLAUDE.md` (both at the repo root). Read both in full, plus `RESEARCH.md`,
> before starting. The docs under `build_artifacts/Phase1_*.md` are superseded
> phase-1 artifacts — do not follow them.
>
> Work ONE chunk at a time, in order (Chunk 0 → Chunk 5). For each chunk:
> (1) re-verify any external API shape it touches against `RESEARCH.md` and its
> live links before writing code — never from memory; (2) implement only what
> that chunk specifies, pulling nothing forward; (3) run the full gate from
> `CLAUDE.md` §4. When the gate is green, make one Conventional Commit for the
> chunk on the `feat/remote-app` branch, then move to the next chunk.
>
> Hard rules (`CLAUDE.md` §1): never weaken tests or tooling config to pass a
> gate — a chunk may UPDATE a test only when it *explicitly* changes a contract,
> and the replacement assertion must be at least as strict; never make a live
> network call in the test path (all HTTP mocked with `respx` or local fixtures;
> `RUN_LIVE` stays off); never commit secrets; never touch `main`. If a chunk's
> gate cannot pass after 3 honest attempts, STOP, write `BLOCKERS.md`, and leave
> the repo on the last green commit.
>
> After the final chunk (Chunk 5), STOP. Fill in only `REVIEW.md`'s two bracketed
> sections (chunks completed; anything flagged for me). Do not declare the build
> verified — image rendering in ChatGPT and the live OAuth login need my eyes.

---

## Alternative — one chunk at a time (manual pacing)

If you'd rather drive it chunk by chunk instead of an autonomous loop, paste this
and repeat it, bumping the number each time:

> Do Chunk 0 from `PLAN.md` only, governed by `CLAUDE.md`. Re-verify any external
> API shape against `RESEARCH.md` and its live links first. Run the full gate
> (`CLAUDE.md` §4); when green, make one Conventional Commit for the chunk on
> `feat/remote-app`, then STOP and wait for me. Do not start the next chunk.

---

## If it stops early

A `BLOCKERS.md` means a chunk failed its gate 3 times. Read it — it names the
chunk, what was tried, the failing command/output, and a hypothesis. The repo is
left on the last green commit, so you can fix the blocker and resume from there.
