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

**Chunks completed:** [ … ]

**Anything I flagged for you:** [ … e.g. SDK version bump and why; the exact
`window.openai` field the widget reads and where it was confirmed; whether the
SDK served RFC 9728 metadata automatically or it had to be added by hand; the
IdP config values consumed; any deviation from PLAN.md and why … ]
