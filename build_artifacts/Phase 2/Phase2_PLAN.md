# PLAN.md — Phase 2: remote, authenticated, ChatGPT-renderable

What to build, in order. Governed by `CLAUDE.md` (repo root); every external contract here is
sourced in `RESEARCH.md`. Read the reconciliation first — it is the result of an
actual read-through of `src/tattoo_feed/` and it constrains every chunk.

---

## Goal

Take the phase-1 stdio MCP server and make it:

1. **Reachable over HTTP** (FastMCP streamable-http), in a container, fronted by
   ngrok as TLS ingress.
2. **Protected** as an OAuth 2.1 resource server, so the public endpoint rejects
   unauthenticated callers — connectable by ChatGPT via OAuth.
3. **Visually renderable in ChatGPT**, by returning an Apps SDK **UI widget** for
   `next_inspiration` instead of a raw MCP image content block (which ChatGPT
   does **not** render inline — see `RESEARCH.md` §1).

Non-goals (carried from phase 1, still true): no video, no carousel expansion
beyond first image, no write-to-Instagram, no token auto-refresh, no GUI beyond
the ChatGPT widget. New non-goal: **no self-hosted authorization server** — we
delegate to an external identity provider and only act as a resource server.

---

## Current-state reconciliation (read before Chunk 0)

A full read of `src/tattoo_feed/` (1,396 lines across 17 files) on
2026-06-14. The architecture is sound and the work is well-contained.

**Clean and untouched by this build:**

- `config.py`, `errors.py`, `models.py`, `imaging.py`, `repositories/*`,
  `graph/client.py`, `services/*` — all pure `core`, zero MCP imports. Leave
  them alone. New auth errors (Chunk 2) are the only `core` change, and they go
  in `errors.py` as `TattooFeedError` subclasses.
- The lazy-config seam (`load_config()` reads env on demand) means the server
  still boots and lists tools with no Instagram credentials. Preserve this.

**The focal change — `server/app.py::next_inspiration` (lines ~138-157):**

```python
preview = fetch_preview(post.image_url, services.http)
image = Image(data=preview, format="jpeg").to_image_content()
return [image, TextContent(type="text", text=_format_post(post))]
```

This returns a native MCP `ImageContent` block. **ChatGPT does not render it
inline** (`RESEARCH.md` §1). Chunk 3 replaces this with an Apps SDK widget
result. Its tests must move to the new contract (see below).

> **Correction (2026-06-16):** the original line here added "Claude understands
> it" implying Claude renders the block inline. Manual testing later showed Claude
> does **not** display image blocks to the user either (see `RESEARCH.md` §1
> correction). It doesn't change Chunk 3 — the widget was the right call — but the
> rationale is "no client shows the raw block to the user," not "only ChatGPT."

**Tests that assert the OLD image contract (must be updated in Chunk 3, not
weakened):**

- `tests/test_server_tools.py::test_next_inspiration_returns_image_then_metadata`
  asserts `blocks[0].type == "image"`.
- `tests/test_image_rendering.py` — asserts the image block is structurally
  valid (base64, `image/jpeg`, ≤640px).
  These are legitimate contract updates under `CLAUDE.md` §1.1: rewrite them to
  assert the new widget contract (resource registered, `_meta.outputTemplate`
  set, image data URL present in `_meta`, decodes to ≤640px JPEG) — at least as
  strict.

**Things to know going in:**

- `_services` is a module-global singleton holding a single sync `httpx.Client`
  and one set of services bound to the single Instagram account. Under HTTP this
  is shared across requests. That is **fine for this single-account demo** (the
  Instagram identity is fixed; OAuth gates *who may call*, not *which IG account*
  is queried). Do not over-engineer per-session state. Note it; don't change it
  unless a chunk says so.
- `main()` is the only `# pragma: no cover` surface and already branches on
  `MCP_TRANSPORT=http` (added during morning setup). Keep the entrypoint thin so
  the auth/transport wiring stays coverable via unit tests on the pieces, not on
  `main()`.
- `mcp==1.27.2` is pinned. The auth API (`AuthSettings`, `token_verifier=`) and
  the `text/html;profile=mcp-app` widget resource must be confirmed present in
  this version (Chunk 0); bump if needed.
- `PyJWT==2.13.0` and `cryptography==49.0.0` are already in `uv.lock` (transitive
  via `mcp`/`pydantic-settings`). Chunk 2 promotes `pyjwt[crypto]` to a **direct,
  pinned** dependency rather than leaning on a transitive pin.

---

## Approved dependencies (phase 2)

Only these may be added/promoted without a `BLOCKERS.md` stop:

- `pyjwt[crypto]==2.13.0` — JWT signature/claim validation in the token verifier
  (promote from transitive to direct).
- A bump of `mcp` to the lowest version that exposes the auth + widget-resource
  API, **only if** Chunk 0 proves `1.27.2` lacks it. Record old→new in the commit.

No others. ngrok and the IdP are external services, not Python packages.

---

## Human pre-requisites (not loop work)

These are decisions/accounts the human provides before/around the loop; the loop
must not invent them:

- **Identity provider choice** (the authorization server). Must support what
  ChatGPT's connector needs: OAuth 2.1, metadata discovery (RFC 8414 / OIDC),
  PKCE, the `resource` indicator (RFC 8707), and either Client ID Metadata
  Documents or Dynamic Client Registration. Auth0 has a documented ChatGPT-MCP
  path (`RESEARCH.md` §5); Stytch / WorkOS / Descope are alternatives. The loop
  consumes the IdP's **issuer URL**, **JWKS URL**, and **audience/resource
  identifier** as config — it does not create the IdP.
- The ngrok authtoken and (ideally) a stable ngrok domain.

---

## Chunk 0 — Baseline and ground-truth

**Goal:** establish the phase-2 branch, confirm the green baseline, and verify
the SDK actually exposes the APIs this plan assumes. The phase-1 docs are already
archived at `build_artifacts/Phase1_*.md` — **do not touch them**. Governance for
this build is the root phase-2 docs (`CLAUDE.md` §"Supersession").

**Deliverables:**

- New branch `feat/remote-app` off the current tip.
- A short `RECONCILIATION.md` (repo root) capturing the SDK-capability findings
  below (so later chunks don't re-derive them).
- Verify, against the installed `mcp` package and `RESEARCH.md` §§1-4:
  - `mcp.server.auth` exposes `AuthSettings` + a `TokenVerifier` protocol and
    `FastMCP(..., auth=, token_verifier=)`.
  - A resource can be registered with mimeType `text/html;profile=mcp-app`.
  - If either is absent in `1.27.2`, bump `mcp` per "Approved dependencies".

**Success gate:** existing gate green with **no source behaviour change**;
`build_artifacts/Phase1_*` untouched; `RECONCILIATION.md` written; `uv.lock`
matches.

---

## Chunk 1 — HTTP transport, formalised

**Goal:** make the streamable-http transport a tested, first-class mode (it was
hand-added during setup; now make it real).

**Deliverables:**

- `server/app.py`: `MCP_TRANSPORT=http` selects streamable-http with
  `mcp.settings.host`/`port` from `MCP_HOST`/`MCP_PORT` (defaults `0.0.0.0`/`8000`),
  stdio otherwise. Keep this inside the thin `main()`/a small helper.
- A small, testable transport-selection helper (pure function mapping env →
  transport choice) so the decision is covered without booting a server.

**Tests (hermetic):**

- Transport-selection helper: env unset → stdio; `MCP_TRANSPORT=http` → http with
  the right host/port.
- The existing `tests/test_server_boot.py` (stdio) still passes unchanged.

**Success gate:** full gate green; stdio boot test unchanged and passing.

---

## Chunk 2 — OAuth 2.1 resource-server protection

**Goal:** the server validates a bearer token on every request and rejects
unauthenticated callers with a spec-compliant `401`, delegating issuance to the
external IdP. (`RESEARCH.md` §§2-3.)

**Deliverables:**

- `core/errors.py`: add typed auth errors as needed (e.g. `AuthError`) —
  `TattooFeedError` subclasses.
- `server/auth.py`: a `TokenVerifier` implementation that validates a JWT:
  signature against the IdP **JWKS** (fetched via the injected `httpx` client,
  cached), `iss` == configured issuer, `aud`/resource == configured canonical
  server URI (RFC 8707 audience binding — **mandatory**, `RESEARCH.md` §2),
  expiry, and required scopes. Returns the SDK's `AccessToken` on success, `None`
  on failure. All network (JWKS) injected so tests mock it.
- New config: issuer URL, JWKS URL, audience/resource, required scopes — read
  from env via `core/config.py` (extend `load_config` or add a sibling loader;
  keep it lazy).
- Wire `FastMCP(..., auth=AuthSettings(issuer_url=..., resource_server_url=...,
  required_scopes=...), token_verifier=...)`. The SDK then serves RFC 9728
  protected-resource metadata and emits the `401 WWW-Authenticate` challenge —
  **confirm this is automatic in the pinned version; if not, serve the metadata
  route explicitly** per `RESEARCH.md` §2.

**Tests (hermetic — generate an RSA keypair in-test, mock JWKS with `respx`):**

- Unauthenticated request → `401` with `WWW-Authenticate: Bearer` containing
  `resource_metadata=`.
- Token signed by the test key with correct `iss`/`aud`/scope/expiry → accepted.
- Wrong audience → rejected. Wrong issuer → rejected. Expired → rejected.
  Missing required scope → rejected (`403`/insufficient_scope).
- Protected-resource metadata document is served at the expected `.well-known`
  path and names the configured AS.

**Success gate:** full gate green; coverage ≥ 90% (verifier is fully unit-tested
without a live IdP).

---

## Chunk 3 — Apps SDK image widget (the render fix)

**Goal:** `next_inspiration` returns a ChatGPT-renderable **widget** showing the
preview image + attribution, instead of a raw image content block.
(`RESEARCH.md` §1.)

**Deliverables:**

- A widget asset `server/widgets/inspiration.html` (static file loaded by Python,
  not generated in code) containing minimal HTML/JS that reads the tool result
  via the `window.openai` bridge and renders an `<img>` plus handle / caption /
  permalink. Keep the JS minimal and dependency-free.
- Register it as an MCP resource at `ui://widget/inspiration.html` with mimeType
  **`text/html;profile=mcp-app`** (`RESEARCH.md` §1.2).
- Rework `next_inspiration` to:
  - put the rendered preview as a **data URL in `_meta`** (forwarded to the
    component, **not** exposed to the model — avoids dumping base64 at the model;
    `RESEARCH.md` §1.4), alongside handle/caption/permalink;
  - set `_meta["openai/outputTemplate"]` and `_meta.ui.resourceUri` to the
    `ui://` URI, and `_meta.ui.csp.resourceDomains` if any external origin is
    referenced (none if we use a data URL);
  - return concise `structuredContent` (handle, permalink, caption — *no* base64)
    so the model has text to narrate;
  - keep a text fallback for the no-unseen-post case.
- **Confirm the exact field path the widget reads** (`window.openai.toolOutput`
  vs the `_meta` forwarding) against the live Apps SDK reference at build time
  before finalising the HTML (`CLAUDE.md` §1.6).

**Tests (hermetic — structural, per `RESEARCH.md` §1; visual render is the
eyeball check):**

- The `ui://widget/inspiration.html` resource is registered and returns mimeType
  `text/html;profile=mcp-app`; its body references an `<img>` and the
  `window.openai` bridge.
- `next_inspiration` result carries `_meta["openai/outputTemplate"]` == the
  `ui://` URI, a data URL in `_meta` that base64-decodes to a JPEG with long edge
  ≤ 640, and `structuredContent` containing the handle + permalink and **no**
  base64.
- **Update** `test_server_tools.py` and `test_image_rendering.py` to this new
  contract (contract change per `CLAUDE.md` §1.1 — at least as strict).

**Success gate:** full gate green; the rewritten image tests pass; coverage
maintained. Visual rendering is explicitly deferred to `REVIEW.md`.

---

## Chunk 4 — Container + ngrok ingress

**Goal:** a reproducible way to run the authenticated HTTP server publicly, with
no secrets baked in. (`RESEARCH.md` §6.)

**Deliverables:**

- `Dockerfile.server` (HTTP server image: source baked, deps via
  `uv sync --frozen --no-dev`, `MCP_TRANSPORT=http`, port exposed). Create it
  fresh per `RESEARCH.md` §6 — any earlier draft has been removed because it
  predates the OAuth design.
- `docker-compose.yml`: `server` + `ngrok` services on a private network; ngrok
  forwards to `server:8000` as plain TLS ingress; all secrets via env (compose
  reads `.env`), **including the IdP config** (issuer, JWKS URL, audience,
  scopes) the server now needs.
- `.env.example`: add the new IdP + ngrok keys with placeholders (issuer, JWKS
  URL, audience, scopes, `NGROK_AUTHTOKEN`).
- A `scripts/` helper or README section: build, run, find the public URL.

**Tests:** the gate is hermetic and does not build images. Add no live tests.
Provide a documented **manual** verification path in `REVIEW.md` instead.

**Success gate:** full gate green (unchanged by this chunk); compose +
`Dockerfile.server` present and self-consistent; `.env.example` complete; no
secret committed (grep clean).

---

## Chunk 5 — Docs, REVIEW, final reconciliation

**Goal:** leave the repo coherent and the human a clear verification path.

**Deliverables:**

- Update `README.md`: the new remote/OAuth/widget architecture, the ChatGPT
  connector setup (auth = OAuth, the server URL), and honest limitations
  (single account, IdP dependency, widget visual-only verification).
- Refresh `REVIEW.md` with the phase-2 human checklist (see that file's
  template): image renders **in ChatGPT** via the widget; the real OAuth login
  completes; the live tunnel serves; `get_feed`/`add_artist` still behave.
- Final re-read of every file changed in chunks 1-4: confirm `core` stays
  MCP-free, `server` holds no business logic, docstrings/annotations updated to
  match new signatures, no dead code, no stray `# type: ignore`.

**Success gate:** full gate green; README and REVIEW coherent; reconciliation
note appended. Then **stop** — do not declare verified.

---

## Map of chunks → reconciliation concerns

| Concern from reconciliation | Handled in |
|---|---|
| Phase-1 docs archived in `build_artifacts/`; governance is the root phase-2 docs | Chunk 0 |
| `mcp` version exposes auth + widget API | Chunk 0 (bump if needed) |
| `core` stays MCP-free; only `errors.py` gains auth types | Chunk 2 |
| Promote `pyjwt[crypto]` to a direct pin | Chunk 2 |
| `next_inspiration` image-block → widget | Chunk 3 |
| Old image tests → new widget contract | Chunk 3 |
| Shared singleton / sync httpx acceptable | noted; unchanged |
| Thin `main()` keeps coverage honest | Chunks 1-2 |
| No secrets in image; ngrok is ingress-only | Chunk 4 |
| Final core/server separation + annotation sweep | Chunk 5 |
