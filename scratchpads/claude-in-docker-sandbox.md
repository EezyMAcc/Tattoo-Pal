# Running Claude Code inside a Docker sandbox — the working recipe

Distilled, reusable reference for authenticating and running **Claude Code
interactively inside an ephemeral (`--rm`) Docker container**, so it can drive
work in a sandbox that can only touch one mounted project folder.

This is the clean version. The blow-by-blow troubleshooting log that got us here
is in `claude-container-setup.md` — read that only if something breaks.

**Verified working: 2026-06-15 (macOS / Apple Silicon host).**

---

## The two problems, and the two-part solution

Running `claude` in a throwaway container hits exactly two walls:

1. **Auth** — interactive browser login can't complete from inside a container
   (the OAuth/PKCE `localhost` callback isn't reachable from the host browser),
   and even if it did, `--rm` wipes `/root/.claude` on exit so it wouldn't
   persist. On macOS the host login lives in the **Keychain**, not a file, so
   there's nothing to mount either.
   → **Solution: forward a long-lived `CLAUDE_CODE_OAUTH_TOKEN` env var.**

2. **The onboarding wizard** — because `/root` is throwaway, every launch looks
   like a brand-new machine, so interactive `claude` shows its first-run
   onboarding/login wizard and **ignores the env token** (which otherwise works
   fine for headless `claude -p`).
   → **Solution: pre-seed `/root/.claude.json` in the image** with onboarding +
   trust flags so the wizard is skipped and the env token is used.

You need **both**. The token alone gets you headless `-p` but not interactive;
the seed alone gets you past the wizard but with no credentials.

---

## Recipe

### 1. Build the image (once per image change)

The `Dockerfile` installs git, Node, `uv`, and `@anthropic-ai/claude-code`, then
bakes in the onboarding seed:

```dockerfile
RUN npm install -g @anthropic-ai/claude-code

# /root is throwaway (--rm) → interactive `claude` would run its onboarding
# wizard and ignore the forwarded token. Seed onboarding state so it doesn't.
# This holds NO credential — only onboarding + workspace-trust flags.
RUN printf '{"hasCompletedOnboarding":true,"theme":"dark","projects":{"/workspace":{"hasTrustDialogAccepted":true}}}' \
        > /root/.claude.json
```

Adjust the project path (`/workspace`) and `theme` to taste. Then:

```bash
docker build -t tattoo-feed-dev .
```

### 2. Mint a clean token on the host (rarely — it's long-lived)

The enemy throughout was **terminal line-wrapping** corrupting the token on copy
or breaking the extraction command on paste. The paste-proof method — short
lines, write to a temp file, eyeball before exporting:

```bash
claude setup-token | tee /tmp/st.txt
grep -oaE 'sk-ant-oat01-[A-Za-z0-9_-]+' /tmp/st.txt | head -1   # confirm it looks whole
export CLAUDE_CODE_OAUTH_TOKEN="$(grep -oaE 'sk-ant-oat01-[A-Za-z0-9_-]+' /tmp/st.txt | head -1)"
echo "length: ${#CLAUDE_CODE_OAUTH_TOKEN}"   # expect ~100
rm -f /tmp/st.txt   # it held the token — delete it
```

If length is 0/short, the token has a char outside `[A-Za-z0-9_-]`; broaden to
`sk-ant-oat01-[!-~]+` (stops only at whitespace/control).

### 3. Launch the container with the token forwarded

`run-loop.sh` does `docker run --rm -it -e CLAUDE_CODE_OAUTH_TOKEN -v "$PWD":/workspace -w /workspace tattoo-feed-dev bash`.

`-e CLAUDE_CODE_OAUTH_TOKEN` (no `=value`) passes the host's value through **by
name**. Run from the **same shell** you exported the token in:

```bash
./run-loop.sh
```

### 4. Verify inside the container

```bash
claude -p "say hi"   # headless — proves the token authenticates API calls
claude               # interactive — should skip the wizard and just work
```

A normal reply from `-p` and a wizard-free interactive session = success.

---

## Why each piece matters (so you can adapt it)

- **`-e VAR` by name, not `-e VAR=...`** — keeps the secret out of the command
  line / shell history; value is pulled from the host env at run time.
- **Only `$PWD` is mounted** — the container can read/write *only* the project
  folder; everything else in the container is throwaway. That's the sandbox
  boundary.
- **No secret is baked into the image** — `/root/.claude.json` carries only
  onboarding/trust flags. The actual credential always arrives at run time via
  the env var. Keep it that way if you commit the image anywhere.
- **`hasCompletedOnboarding` + `theme`** skip the login/theme wizard;
  **`projects.<path>.hasTrustDialogAccepted`** skips the "do you trust this
  folder?" prompt that otherwise appears next. Set the path to your `-w` workdir.

---

## Gotchas / things to re-check on a new setup

- The token is **single-line, ~100 chars**, format `sk-ant-oat01-…`. Any embedded
  newline → `Header has invalid value: 'Bearer sk-ant-oat01-0'`. Truncation →
  `Not logged in · Please run /login`. Both come from line-wrap; use the
  file-based capture above, never a raw long-line copy/paste.
- `claude setup-token` prints the token on **stdout** mixed with UI; the browser
  prompt is on **stderr** (stays visible even when stdout is piped).
- A future Claude Code version could rename the env var or change the
  onboarding-state keys. If interactive login returns after an upgrade, run
  `claude doctor` and inspect `~/.claude.json` on a host install to see the
  current keys, then update the seed.

## Fallback if container auth ever fights you again

**Host-orchestrated mode:** run Claude Code on the **host** (already logged in via
Keychain) and have it run only the *gate* inside the container via
`docker run … bash -lc '…'`. Trade-off: Claude itself is no longer sandboxed —
only the commands it runs are. We chose the in-container model to sandbox Claude
fully; this is the escape hatch.
