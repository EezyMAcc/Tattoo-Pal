# REVIEW.md — Phase 2 human verification

Run top to bottom after the loop reports Chunk 5 green. The loop fills in the two
bracketed sections at the end before stopping. As in phase 1, the things that
matter most here are the ones automated gates **cannot** confirm: the image
actually rendering in ChatGPT, and the real OAuth login.

-----

## 0. First glance

- [ ] `BLOCKERS.md`? If present, read it first — it says which chunk stopped and
  why. Everything below still applies to the chunks that landed.
- [ ] `git log --oneline` on `feat/remote-app` — one clean commit per chunk
  (0 → 5), plus the Chunk 0 archival commit. `main` untouched.
- [ ] `git status` clean.

## 1. Gate still green (in the container)

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

- [ ] All four exit 0. Coverage ≥ 90%.
- [ ] The rewritten `next_inspiration` / image tests assert the **widget**
  contract (outputTemplate meta + registered `ui://` resource + data URL in
  `_meta`), not the old image block. Confirm they did not just get weakened.

## 2. Secrets & archival hygiene

- [ ] `git grep` for the token prefix / `client_secret` / private-key markers →
  nothing committed. `.env` not staged.
- [ ] Phase-1 docs are archived in `build_artifacts/` as `Phase1_*.md` and
  untouched; the phase-2 governance docs live at the repo root.

## 3. Bring it up (container + tunnel)

- [ ] `.env` has real Instagram creds, the IdP issuer/JWKS/audience/scopes, and
  `NGROK_AUTHTOKEN`.
- [ ] `docker compose up --build` brings up `server` + `ngrok`.
- [ ] Public URL resolves (ngrok inspector at `http://localhost:4040`).

## 4. Auth actually gates (the OAuth check — gates can't do this live)

- [ ] `curl https://<public-url>/mcp` with **no** token → `401` with a
  `WWW-Authenticate: Bearer ... resource_metadata=...` header.
- [ ] `curl https://<public-url>/.well-known/oauth-protected-resource` → metadata
  naming your IdP.
- [ ] In ChatGPT, add the connector (URL = public `/mcp`, Auth = **OAuth**).
  The login flow completes and the connector lists every tool.
- [ ] A request with an expired/garbage token is refused (not served).

## 5. THE EYEBALL CHECK (image rendering in ChatGPT — gates cannot verify)

This is the reason phase 2 exists. Look with your eyes:

- [ ] Ask ChatGPT to call `next_inspiration`. The preview image **renders inline
  via the widget** (not as text, not as a broken frame).
- [ ] It is the **right image** for the post (cross-check the permalink shown).
- [ ] Orientation correct (EXIF was applied then stripped); size is a sensible
  preview (≤ 640px long edge), not full-res or tiny.
- [ ] A carousel post shows its **first** image.
- [ ] The model's narration (from `structuredContent`) has the handle + permalink
  and does **not** contain a wall of base64 (data lives in `_meta`).

## 6. Functional smoke test (unchanged behaviours still work)

- [ ] `add_artist` with a real professional handle → succeeds; a personal account
  → clean typed error, no stack trace.
- [ ] `get_feed` → newest-first, no videos.
- [ ] `save_to_inspiration` then `list_inspiration` → saved item present with
  handle attached.
- [ ] `record_preference` → assistant proposes & asks to confirm before writing.

## 7. Code review pass

- [ ] `core` still has zero MCP/HTTP/OAuth imports; `server/` holds no business
  logic. The token verifier lives in `server/`, not `core/`.
- [ ] New files small and single-purpose; docstrings/annotations match new
  signatures; errors typed.
- [ ] README explains the remote/OAuth/widget setup and the honest limitations.

-----

## Loop fills these in before stopping

**Chunks completed:** Chunks 0 → 5 all committed green on `feat/remote-app`.

- Chunk 0 — Baseline + SDK capability verification (`RECONCILIATION.md`)
- Chunk 1 — HTTP transport formalised (`resolve_transport` helper, tests)
- Chunk 2 — OAuth 2.1 resource-server protection (`server/auth.py`,
  `IdpTokenVerifier`, `AuthError` in `errors.py`)
- Chunk 3 — Apps SDK image widget (`server/widgets/inspiration.html`,
  `next_inspiration` returns widget result with `_meta` image data URL)
- Chunk 4 — Container + ngrok ingress (`Dockerfile.server`,
  `docker-compose.yml`, `.env.example`, `scripts/run-server.sh`)
- Chunk 5 — Docs, REVIEW, final reconciliation (this commit)

**Anything I flagged for you:**

1. **No `mcp` version bump needed.** `mcp==1.27.2` exposes all required APIs
   (`AuthSettings`, `TokenVerifier`, `AccessToken`, resource registration with
   `text/html;profile=mcp-app`). See `RECONCILIATION.md` for the verified
   symbol list.

2. **RFC 9728 metadata is served automatically by the SDK.** When
   `mcp.settings.auth` is set to an `AuthSettings` instance, FastMCP
   automatically serves `/.well-known/oauth-protected-resource` and emits the
   `401 WWW-Authenticate: Bearer resource_metadata=...` challenge. No explicit
   route or middleware was added by hand.

3. **`window.openai` widget data path.** The widget (`server/widgets/inspiration.html`)
   tries two paths confirmed in `RESEARCH.md` §1.4:
   - Primary: `window.openai.toolOutput._meta` (host forwards `_meta` before
     the frame loads).
   - Fallback: a `message` event listener for
     `ui/notifications/tool-result` → `params._meta`.
   The image data URL, handle, caption, and permalink all travel through
   `_meta` (not `structuredContent`) so the base64 blob never reaches the
   model. Verify the image actually renders in ChatGPT (§5 above).

4. **`MCP_AUTH_AUDIENCE` is the RFC 8707 audience.** This value must appear
   verbatim as the `aud` claim in tokens your IdP issues, AND must match the
   resource indicator the ChatGPT connector sends. When the ngrok URL changes,
   update `MCP_AUTH_AUDIENCE` in `.env` **and** reconfigure the IdP. A stable
   ngrok domain (§3 in README) prevents this churn.

5. **Scope enforcement is automatic.** The SDK's `RequireAuthMiddleware`
   checks `AccessToken.scopes` against `AuthSettings.required_scopes` and
   returns `403 insufficient_scope` when a scope is missing.
   `IdpTokenVerifier.verify_token` only validates the JWT shape; it never
   checks scopes itself.

6. **JWKS caching is in-process only.** `IdpTokenVerifier` caches the JWKS
   keys in memory for the lifetime of the process. A key rotation by the IdP
   will require a server restart to pick up new keys. This is acceptable for a
   single-account demo but worth noting for production hardening.

7. **Single-account limitation.** The `_services` singleton is built once and
   bound to the one Instagram account set via `IG_USER_ID`. OAuth controls who
   may call the server, not which Instagram account is queried. Multi-account
   support is explicitly out of scope.
