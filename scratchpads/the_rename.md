# The rename — `tattoo-feed` → `Tattoo Pal`

A planning reference for renaming the project. It records **what the old name
touches**, **what should change vs. stay**, the **three layers** the name lives
in, and — most importantly — **why one layer gets renamed and another
deliberately doesn't.** Nothing here has been executed; this is the map you decide
from.

The guiding principle: *the product name and the code's internal name are two
different things, and they do not have to match.* Most of the cost — and all of
the risk — of a rename comes from conflating them.

---

## 0. Where the name actually lives (the footprint)

"The name" is not one string; it appears in three independent layers, surveyed
from the repo as it stands:

- **Layer 1 — Product / display name.** The human- and ChatGPT-facing label:
  the word "Tattoo Feed" in prose, and the MCP server's display name string.
- **Layer 2 — Repo & directory.** The local folder `tattoo-feed/` and the GitHub
  remote.
- **Layer 3 — Internal code identifiers.** The Python import package
  `tattoo_feed`, the distribution name `tattoo-feed`, the Docker image name, the
  Compose volume/network names, the `python -m tattoo_feed.server.app` entrypoint.

They look like "the same rename" but have wildly different costs and payoffs.
Treating them as one find-and-replace is the trap.

---

## 1. Layer 1 — Product / display name  → **CHANGE** (cheap, high payoff)

This is the part that actually *makes the rename real* — what a person or ChatGPT
sees.

**What it touches:**
- Prose "Tattoo Feed" / "tattoo-feed" as a title in the docs: `README.md`,
  `RETROACTIVE_PRD.md`, and the headers/mentions in `PLAN.md`, `REVIEW.md`,
  `CLAUDE.md`, `BUILD.md`, `RESEARCH.md`, `RECONCILIATION.md`.
- **The MCP server display name** — `src/tattoo_feed/server/app.py` (~line 70),
  `FastMCP("tattoo-feed", …)`. This is the label ChatGPT shows for the connector,
  so it is genuinely user-facing.

**Why change it:** this layer *is* the product identity. If the docs and the
connector still say "Tattoo Feed," the rename hasn't happened in any way a user
would notice.

**Why it's safe/cheap:**
- The server-name change is a single string literal — **no test asserts it**
  (verified: nothing in `tests/` references the `"tattoo-feed"` string), and it
  does **not** affect OAuth (the RFC 8707 audience is bound to the server *URL*,
  not its display name).
- Doc edits are prose; they can't break the gate.

**Decision to make:** displayed as `Tattoo Pal` (prose) and `tattoo-pal` (the
machine-ish server name string)? Recommended: yes to both.

---

## 2. Layer 2 — Repo & directory  → **CHANGE** (with two gotchas)

**What it touches:**
- Local directory `tattoo-feed/` → `tattoo-pal/` (`mv`).
- GitHub remote. Current state: the only remote is `demo` →
  `github.com/EezyMAcc/mcp-loop-build-demo.git`. There is **no** `tattoo-feed`
  remote to rename — you create a *new* `tattoo-pal` repo and add it as `origin`.

**Steps (run by a human, not mid-session):**
```bash
# from the parent dir, after committing/cleaning the working tree
mv tattoo-feed tattoo-pal
cd tattoo-pal
# create the repo on GitHub first (gh repo create tattoo-pal ... or the web UI)
git remote add origin https://github.com/<you>/tattoo-pal.git
git push -u origin <branch>
# keep or drop the old demo remote as you like:
# git remote remove demo
```

**Gotcha A — Claude Code project memory is keyed on the absolute path.** History
and memory live under `…/.claude/projects/-Users-…-tattoo-feed/`. Renaming the
directory changes the path, so that context **does not follow** — you effectively
start a fresh project path. Not fatal, but expected.

**Gotcha B — Docker Compose derives its project name from the directory.** Today
the volumes/networks are `tattoo-feed_internal` and `tattoo-feed_tattoo-data`.
After the `mv` they become `tattoo-pal_*`, so the old data volume orphans. It only
holds demo JSON, so it's harmless — run `docker compose down -v` before the move
to keep things tidy.

---

## 3. Layer 3 — Internal code identifiers  → **LEAVE AS `tattoo_feed`** (deliberately)

**What it would touch (the scope that argues against it):**
- The import package `src/tattoo_feed/` and **~50 import sites** across `src/` and
  `tests/` (`from tattoo_feed… import …`).
- `pyproject.toml` — `name = "tattoo-feed"` and the wheel `packages` entry — plus
  a regenerated `uv.lock`.
- The entrypoint `python -m tattoo_feed.server.app` in `Dockerfile.server`,
  `docker-compose.yml`, and `.github/workflows/ci.yml`.
- The gate command itself: `--cov=src/tattoo_feed`.
- The Docker image name `tattoo-feed-server` and Compose volume/network names.

**Why deliberately NOT change it — the reasoning, since this is the crux:**

1. **The internal name is invisible to users.** Nobody types `import tattoo_feed`
   except the code. The product can be "Tattoo Pal" while the package stays
   `tattoo_feed` — this mismatch is *normal* (products routinely ship under a
   marketing name different from their internal/codename package).
2. **All cost, no functional gain.** Renaming the package changes nothing about
   what the software does. It's pure churn.
3. **It touches the most dangerous surfaces.** The rename would hit the
   **entrypoint**, the **Docker CMD**, the **CI workflow**, and the **gate
   command** simultaneously — exactly the load-bearing wiring where a typo means
   "image builds but won't start" or "CI silently measures nothing" (cf. the
   `--cov=src/tattoo-feed` vs `tattoo_feed` mishap we already hit). High blast
   radius for a cosmetic win.
4. **The product rename does not depend on it.** Layers 1+2 fully deliver the
   rename a user experiences. Layer 3 is orthogonal.

**If you ever do want full internal consistency:** treat it as its own deliberate
refactor — a dedicated branch, one commit, and a **full gate re-run afterwards**
(`ruff` / `mypy` / `pytest --cov`) — never as a rider on the product rename. Doing
it then keeps the blast radius contained and reviewable.

---

## 4. Leave entirely (do not touch)

- **`build_artifacts/Phase 1/*`** — the historical record of build 1. The old name
  is *correct* there; rewriting it would corrupt the archive.
- Anything under Layer 3, per §3.

---

## 5. The decision in one table

| Layer | Example | Verdict | Why |
|---|---|---|---|
| 1. Display name | docs prose, `FastMCP("tattoo-feed")` | **Change** | It *is* the product identity; cheap; safe (no test/OAuth dependency) |
| 2. Repo & dir | folder name, GitHub remote | **Change** | The repo should carry the product's name; mind the two gotchas |
| 3. Internal code | `tattoo_feed` package, dist, image, entrypoint | **Leave** | Invisible to users; pure churn; touches entrypoint/CI/gate; rename doesn't need it |
| — Archive | `build_artifacts/Phase 1/*` | **Leave** | Historical record; old name is correct |

---

## 6. Suggested execution order

1. Land any outstanding work and get a clean tree (the recent doc edits, PRD, etc.).
2. **Layer 1:** doc prose + the one server-name string → commit (`docs: rename
   product to Tattoo Pal`). Re-run the gate (doc-only, but cheap insurance).
3. **Layer 2:** `docker compose down -v` → `mv` the directory → create the GitHub
   repo → add `origin` → push. (Accept the Claude-memory path reset.)
4. **Layer 3:** *skip*, unless/until you consciously want an internal refactor —
   then do it standalone with a full gate re-run.

The whole user-visible rename is steps 2–3. Step 4 is a separate, optional project.

---

## 7. What was actually changed (execution log — 2026-06-18)

A partial Layer 1 pass was applied on branch `the-rename`, then the server change
was deliberately reverted. Current state of the working tree:

**Changed (and kept):**
- `README.md` — three prose "Tattoo Feed" → "Tattoo Pal" mentions (intro,
  read-and-curate note, and the "How it works" diagram). The ASCII diagram's
  right-hand `Instagram / Business / Discovery` labels were nudged left by one
  column to restore alignment, since "Pal" is one character shorter than "Feed".
- `RETROACTIVE_PRD.md` — the title and the intro sentence.
- `src/tattoo_feed/__init__.py` — the package docstring's product name
  ("Tattoo Feed: an MCP server…" → "Tattoo Pal: …"). This was a Layer 1 prose
  spot the original §1 survey missed; it is the product name, not the
  `tattoo_feed` identifier, so it falls on the "change" side of the line.

**Reverted (left as `tattoo-feed`):**
- `src/tattoo_feed/server/app.py` — the MCP server display-name string. Both
  `FastMCP("tattoo-feed", …)` sites were changed to `"tattoo-pal"` and then
  reverted on request. So the connector ChatGPT shows is **still labelled
  `tattoo-feed`** — the one user-facing piece of Layer 1 that is *not* yet done.

**Not touched (per §3/§4, as planned):** all Layer 3 identifiers (`tattoo_feed`
package, `pyproject.toml` dist name, `--cov=src/tattoo_feed`, the
`python -m tattoo_feed.server.app` entrypoint, `TattooFeedError`,
`TATTOO_FEED_DATA_DIR`, Docker image / compose / `run-server.sh` references),
Layer 2 (directory + remote), and the `build_artifacts/` archive.

**Gate:** ran green with all edits in place (ruff clean, mypy clean, 135 tests
passing at 100% coverage) before the server revert. The kept changes are
docs/docstring-only and don't affect the gate.

**Status:** uncommitted; pausing here. To finish the user-visible rename later,
the open item is the server display name in `app.py` (revert of the revert),
then Layer 2.
