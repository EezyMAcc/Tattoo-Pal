# Claude Code in a Docker container — setup notes & troubleshooting

Working notes for getting **Claude Code authenticated and running inside the
`tattoo-feed-dev` Docker container**, so it can drive the autonomous phase-2
`/loop` build from inside the sandbox. Written so it can be dropped into a fresh
Claude chat to continue, and later distilled into clean setup instructions.

Status as of 2026-06-15: **auth not yet working** — stuck on getting a clean
`CLAUDE_CODE_OAUTH_TOKEN` into the container. Approach is sound; the blocker is
copy/paste mangling the token. See "Current blocker" and "Robust method".

---

## Goal

Run `claude` (Claude Code) **inside** the container (the "sandboxed" model the
user chose), open a fresh chat, and paste the build prompt. The container runs
the gate with bare `uv run …`. For that, `claude` must be authenticated inside
the container.

## Environment

- **Host:** macOS (Apple Silicon), zsh.
- **Dev image:** `tattoo-feed-dev`, built from the repo-root `Dockerfile`
  (debian-slim + git, Node.js, `uv`, and `@anthropic-ai/claude-code`).
- **Launcher:** `./run-loop.sh` →
  `docker run --rm -it -e CLAUDE_CODE_OAUTH_TOKEN -v "$PWD":/workspace -w /workspace tattoo-feed-dev bash`.
- **Container is ephemeral** (`--rm`); only the project folder is mounted at
  `/workspace`; the container home (`/root`) is throwaway and wiped on exit.

## The core problem: authenticating Claude Code inside the container

Two hard constraints rule out the obvious approaches:

1. **Interactive browser login fails from inside the container.** Running
   `claude` and logging in opens `claude.ai`, but the OAuth/PKCE flow expects a
   `localhost` callback that the *host* browser can't reach back into the
   container, and the handshake breaks with:
   `Invalid OAuth Request — Missing code_challenge parameter`.
2. **Even if it worked, `--rm` wipes `/root/.claude` on exit**, so a login would
   not persist across runs.

So the intended approach is a **long-lived token** in the
`CLAUDE_CODE_OAUTH_TOKEN` env var, generated on the host with
`claude setup-token` and **forwarded into the container**.

**Mounting host credentials is NOT an option on macOS:** there is no
`~/.claude/.credentials.json` to mount — the login is stored in the **macOS
Keychain** (confirmed: `ls ~/.claude/.credentials.json` → absent). So the token
env var is the only route.

## What's already set up

- **`run-loop.sh`** forwards the token with `-e CLAUDE_CODE_OAUTH_TOKEN` and
  prints a warning if the var is unset on the host. (`-e VAR` with no `=value`
  passes the host's value through by name.)
- **`PROMPTS.md`** documents the morning flow: `setup-token` → `export` →
  `./run-loop.sh` → `claude`.

## The token-capture saga (what we tried, and why each failed)

| # | Attempt | Symptom | Root cause |
|---|---------|---------|-----------|
| 1 | `claude` login inside container | browser: `Invalid OAuth Request — Missing code_challenge` | interactive login can't complete from a container (no reachable localhost callback) |
| 2 | exported token, ran `claude` | still showed sign-in | (needed to verify the var actually reached the container) |
| — | `printenv CLAUDE_CODE_OAUTH_TOKEN` *inside* container | prints `sk-ant-oat01-07…` | forwarding **works**; token is present in the container |
| 3 | `claude -p "say hi"` | `API Error: Header '14' has invalid value: 'Bearer sk-ant-oat01-0` | token value contained a **newline/CR** — HTTP header values can't span lines. The token was copy-pasted and **wrapped across terminal lines**, embedding breaks. |
| 4 | strip whitespace: `export VAR="$(printf '%s' "$VAR" \| tr -d '[:space:]')"` then `claude -p` | `Not logged in · Please run /login` | the copy didn't just add a newline — it **corrupted/truncated** the token. Stripping can't rebuild missing characters. |
| 5 | capture directly: `export VAR="$(claude setup-token \| tr -d '[:space:]')"` | length **6267** | command substitution swallowed the **entire interactive UI** (ANSI codes, browser URL, prompts), not just the token |
| 6 | grep-extract one-liner | length **0**, `zsh: command not found: sk-ant-oat01-…` | the long command **wrapped across two lines on paste**; zsh parsed the pattern as a separate command, so `grep` ran with no pattern. NOT an approach failure — a paste/line-wrap failure of the command itself. |

### Key facts learned

- The token **does** forward into the container correctly via `-e`.
- `claude` in the image **does** read `CLAUDE_CODE_OAUTH_TOKEN` (attempt 3 proves
  it — it tried to use the value as a Bearer header).
- Token format: `sk-ant-oat01-…` (long, single line, ~100 chars expected).
- The recurring enemy is **terminal line-wrapping** corrupting either the token
  (when copied) or the command (when pasted). Every fix must avoid long-line
  copy/paste.
- `claude setup-token` prints the token on **stdout** mixed with a lot of UI;
  the browser prompt appears on **stderr** (so it stays visible even when stdout
  is captured/piped).

## Current blocker

Getting a **clean, complete token** into `CLAUDE_CODE_OAUTH_TOKEN` on the host.
Both the corruption (copy) and the junk-capture (command-substitution) and the
command-wrap (paste) stem from long strings wrapping in the terminal.

## Robust method (paste-proof, inspectable) — TRY THIS NEXT

Run on the **host**, each line short enough not to wrap. Writes `setup-token`
output to a temp file, extracts just the token, lets you eyeball it, then exports:

```bash
claude setup-token | tee /tmp/st.txt
```
```bash
grep -oaE 'sk-ant-oat01-[A-Za-z0-9_-]+' /tmp/st.txt | head -1
```
(Confirm that printed a single, full-looking token. Then:)
```bash
export CLAUDE_CODE_OAUTH_TOKEN="$(grep -oaE 'sk-ant-oat01-[A-Za-z0-9_-]+' /tmp/st.txt | head -1)"
```
```bash
echo "length: ${#CLAUDE_CODE_OAUTH_TOKEN}"   # expect ~100
```
```bash
rm -f /tmp/st.txt   # it held the token — delete it
```

- If **length is still 0/short**, the token uses a character outside
  `[A-Za-z0-9_-]`. Broaden the class (stops only at whitespace/control):
  `grep -oaE 'sk-ant-oat01-[!-~]+'`.
- Then, in the **same shell**: `./run-loop.sh`, and inside the container test
  with `claude -p "say hi"`. A normal reply = success.

> Why `tee`/file instead of the one-liner: short lines don't wrap on paste, and
> you can *see* the extracted token before committing to it.

## Things still to verify / open questions

- Exact character set of `sk-ant-oat01-` tokens (is `[A-Za-z0-9_-]` complete?).
- How long a `setup-token` token stays valid before re-auth is needed
  (expected: long-lived / CI-grade, so this is a rare one-time step).
- Whether a future Claude Code version changes the env var name or login UX.

## Draft of the clean future setup (to refine once it works)

On the host, from the repo root:

1. `docker build -t tattoo-feed-dev .`  *(once per image change)*
2. Mint a clean token (the "Robust method" above), ending with
   `export CLAUDE_CODE_OAUTH_TOKEN=…` in the current shell.
3. `./run-loop.sh`  *(forwards the token into the container)*
4. Inside the container: `claude` → already authenticated → paste the build
   prompt from `PROMPTS.md`.

## Files involved

- `run-loop.sh` — launches the container, forwards `-e CLAUDE_CODE_OAUTH_TOKEN`,
  warns if unset.
- `PROMPTS.md` — the build launch prompt + the morning flow.
- `Dockerfile` — the dev image (installs Claude Code).
- this file — the troubleshooting log.

## Alternative if the token keeps fighting us

The **host-orchestrated** model avoids container auth entirely: run Claude Code
on the host (already logged in via Keychain) and have it run only the *gate*
inside the container via `docker run … bash -lc '…'`. We deliberately moved away
from this to get Claude sandboxed, but it's the fallback if token injection stays
painful. (Trade-off: Claude itself is not sandboxed; only the gate runs in the
container.)
