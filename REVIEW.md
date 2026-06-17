# REVIEW.md — Phase 3 human verification

Run top to bottom after the loop reports chunk 2 green. The loop fills in the
"Chunks completed" section at the end before stopping. As in phase 2, the things
that matter most are the ones automated gates **cannot** confirm: the image
rendering in ChatGPT and the real OAuth login.

---

## 0. First glance

- [ ] `BLOCKERS.md`? If present, read it first — it says which chunk stopped and
  why. Everything below still applies to the chunks that landed.
- [ ] `git log --oneline` on `refactor/auth` — one clean commit per chunk (0 → 2).
  `main` untouched.
- [ ] `git status` clean.

## 1. Gate still green (in the container)

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

- [ ] All four exit 0. Coverage ≥ 90% (target: 100%).

## 2. Parity confirmation (what must not have changed)

- [ ] **Tool set unchanged.** The boot test (`test_server_boot.py`) passes, and
  `list_tools()` returns exactly these 11 names in any order:
  `list_artists`, `add_artist`, `remove_artist`, `get_feed`, `next_inspiration`,
  `save_to_inspiration`, `list_inspiration`, `remove_from_inspiration`, `reset_seen`,
  `record_preference`, `get_preference_summary`. No tool added, removed, or renamed.
- [ ] **stdio still boots unauthenticated.** With dummy env vars
  (`IG_ACCESS_TOKEN=x IG_USER_ID=x`), `uv run python -m tattoo_feed.server.app`
  starts over stdio with no auth challenge. Ctrl-C to exit.
- [ ] **`core` stays MCP-free.** `grep -r "from mcp\|import mcp\|FastMCP" src/tattoo_feed/`
  returns hits only inside `src/tattoo_feed/server/`.

## 3. Secrets & archival hygiene

- [ ] `git grep` for token prefixes / `client_secret` / private-key markers →
  nothing committed. `.env` not staged.
- [ ] Phase-1 docs archived in `build_artifacts/Phase 1/` (`Phase1_*.md`) and
  phase-2 docs in `build_artifacts/Phase 2/` (`Phase2_*.md`) — untouched.
  Root `CLAUDE.md` / `PLAN.md` are the phase-3 governance docs.

## 4. Bring it up (container + tunnel)

- [ ] `.env` has real Instagram creds, the IdP issuer/JWKS/audience/scopes, and
  `NGROK_AUTHTOKEN`.
- [ ] `docker compose up --build` brings up `server` + `ngrok`.
- [ ] Public URL resolves (ngrok inspector at `http://localhost:4040`).

## 5. Auth actually gates (live check — the gate cannot do this)

- [ ] `curl https://<public-url>/mcp` with **no** token → `401` with a
  `WWW-Authenticate: Bearer ... resource_metadata=...` header.
- [ ] `curl https://<public-url>/.well-known/oauth-protected-resource` → `200`;
  body names your IdP (`resource`, `authorization_servers`, `scopes_supported`).
- [ ] In ChatGPT, add the connector (URL = public `/mcp`, Auth = **OAuth**). The
  login flow completes and the connector lists all 11 tools.
- [ ] A request with an expired/garbage token is refused (not served).

  **Watch for `421 Misdirected Request / Invalid Host header`** — see note (2)
  in the "Flagged items" section below.

## 6. THE EYEBALL CHECK (image rendering in ChatGPT — the gate cannot verify this)

This is what the product is for. Look with your eyes:

- [ ] Ask ChatGPT to call `next_inspiration`. The preview image **renders inline
  via the widget** (not as text, not as a broken frame).
- [ ] It is the **right image** for the post (cross-check the permalink shown).
- [ ] Orientation correct (EXIF applied then stripped); size is a sensible preview
  (≤ 640px long edge), not full-res or tiny.
- [ ] The model's narration (from `structuredContent`) has the handle + permalink
  and does **not** contain a wall of base64 (data travels in `_meta`).

## 7. Functional smoke test

- [ ] `add_artist` with a real professional handle → succeeds; a personal account →
  clean typed error, no stack trace.
- [ ] `get_feed` → newest-first, no videos.
- [ ] `save_to_inspiration` then `list_inspiration` → saved item present with handle.
- [ ] `record_preference` → assistant proposes and asks to confirm before writing.

## 8. Phase-3 specific checks

- [ ] **No module-level `mcp` global.**
  `grep -n "^mcp = FastMCP" src/tattoo_feed/server/app.py` → no results.
- [ ] **No private-attribute auth write.**
  `grep -rn "_token_verifier" src/` → no results.
- [ ] **`# pragma: no cover` is just the `run()` tail.** In `server/app.py`, only
  `main()` and the `if __name__ == "__main__"` guard carry the pragma; the factory
  and all tool functions are fully covered by the gate.
- [ ] **Behavioural wiring test confirms HTTP auth.** `pytest tests/test_server_auth.py -v`
  — the four HTTP integration tests (401 / valid-admitted / 403 / metadata) pass
  against the real `build_server` factory; JWKS mocked with `respx`, no live IdP.
- [ ] **Seam doc closed.**  `scratchpads/auth-wiring-seam.md` is marked RESOLVED at
  the top.

---

## Loop fills these in before stopping

**Chunks completed:** Chunks 0 → 2 all committed green on `refactor/auth`.

- Chunk 0 — Baseline + SDK contract lock (`PHASE3_RECONCILIATION.md`; no `src/`
  change; gate confirmed green before any phase-3 work)
- Chunk 1 — Factory + constructor-injected auth; module-level `mcp` global deleted;
  `@mcp.tool()` / `@mcp.resource()` decorators removed; `build_server(auth_cfg)`
  factory added; `main()` rewritten to use the factory; `# pragma` shrunk to the
  `run()` tail; HTTP wiring tests and registration test added
- Chunk 2 — Docs, REVIEW delta, seam closed (`scratchpads/auth-wiring-seam.md`
  marked RESOLVED; `scratchpads/phase-3-motivation.md` branch name fixed;
  README updated; this REVIEW.md written)

**Flagged items:**

1. **The auth-wiring seam (Parts 1–3) is closed.** The two structural fragilities
   documented in `scratchpads/auth-wiring-seam.md` are resolved:
   - Auth is now configured through `FastMCP`'s public `auth=` / `token_verifier=`
     constructor parameters inside `build_server(auth_cfg)` — no private-attribute
     write (`mcp._token_verifier = verifier` is gone).
   - The `# pragma: no cover` region shrank to just the transport-dispatch /
     `run()` tail. The auth wiring itself is covered by the hermetic wiring test
     in `test_server_auth.py`, which drives `build_server(auth_cfg)` through a
     Starlette `TestClient`: tokenless → `401`, valid token admitted, wrong scope
     → `403`, metadata served at `/.well-known/oauth-protected-resource`.

2. **The `421 Invalid Host header` (Bug 2 in `auth-wiring-seam.md §4`) is NOT
   resolved by phase 3.** The SDK bakes the allowed-host list into
   `settings.transport_security` at `FastMCP` construction time (from the `host`
   constructor parameter, defaulting to `'127.0.0.1'`). The `server.settings.host`
   override that `main()` applies after `build_server()` returns does not
   retroactively update `transport_security`. If the 421 reappears under ngrok,
   follow the fix described in `scratchpads/auth-wiring-seam.md §4`: either pass
   `host=t.host` into the `FastMCP` constructor (which requires threading the
   transport config into `build_server`), or set `transport_security` explicitly
   after construction.

3. **stdio remains unauthenticated.** `build_server(None)` constructs a plain
   `FastMCP` with no auth settings; `main()` takes this path when
   `MCP_TRANSPORT != "http"`. No token is required to browse tools locally.

4. **JWKS caching is in-process only.** `IdpTokenVerifier` caches JWKS keys in
   memory for the process lifetime. A key rotation by the IdP requires a server
   restart. (Unchanged from phase 2; acceptable for a single-account demo.)

5. **Single-account limitation unchanged.** The `_services` singleton is bound to
   one Instagram account (`IG_USER_ID`). OAuth controls who may call; multi-account
   support is out of scope.
