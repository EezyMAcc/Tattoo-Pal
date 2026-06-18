# PLAN.md — Phase 3: the auth-wiring refactor

The build plan for **phase 3**, on branch **`refactor/auth`**. Work the chunks in
order; each starts green and ends green, one Conventional Commit per chunk. This
file is *what* to build; the root `CLAUDE.md` (to be written) governs *how*; the
motivation and success criteria live in `scratchpads/phase-3-motivation.md`.

Phase 3 is a **behaviour-preserving refactor**, not a feature. The external
behaviour of the server does not change; its internal construction does.

---

## 1. Why (one paragraph)

Phase 1 built the server as a module-level `mcp = FastMCP(...)` singleton with
`@mcp.tool()` decorators applied at import — correct for a stdio-only, no-auth
server. Phase 2 added OAuth, which needs runtime, env-derived config the server
object must receive — but the import-time singleton means `mcp` is built before
that config exists, so phase 2 fell back to a private post-construction write
(`mcp._token_verifier = verifier`) inside the `# pragma: no cover` `main()`. That
seam puts the auth wiring on **unsupported API** and **outside the gate** (full
anatomy: `scratchpads/auth-wiring-seam.md`). Phase 3 removes the module-level
global and builds the server in a **factory** that injects auth through the
**public constructor parameters**, proven by a hermetic wiring test — while
keeping unauthenticated **stdio** as a first-class local mode.

---

## 2. Scope & parity contract (must not change)

This is a refactor; these invariants are the definition of "behaviour preserved":

- **The MCP surface is identical** — the same 11 tools and the one widget
  resource, same names, same descriptions, same return shapes. Nothing added,
  removed, or renamed.
- **stdio runs unauthenticated** (local dev), exactly as today. Auth is never
  mandatory.
- **HTTP rejects unauthenticated requests with `401`** before any tool runs, and
  serves `/.well-known/oauth-protected-resource`. Valid token → admitted;
  insufficient scope → `403`.
- **`core` stays MCP-free.** The two-layer split is untouched. `server/auth.py`
  (`AuthConfig`, `load_auth_config`, `IdpTokenVerifier`) and the services layer
  (`_Services`, `_build_services`, `_get_services`) are reused **unchanged**.

---

## 3. Target shape of `server/app.py` (the "after" picture)

Before → after, at a glance:

```text
BEFORE                                  AFTER
mcp = FastMCP(...)            # global   (deleted — no module-level server)
@mcp.tool() def list_artists  ...        def list_artists(...)      # plain fn
@mcp.resource(...) _widget    ...        def _widget_inspiration(...)  # plain fn
main(): build mcp at import,             build_server(auth_cfg) -> FastMCP
        write mcp._token_verifier            (constructor-injects auth)
        (under pragma)                   main(): pick transport -> build_server(...)
                                                 -> run   (pragma shrunk to run tail)
```

Concretely:

- **Tools and the widget become module-level *plain* functions** — the
  `@mcp.tool()` / `@mcp.resource()` decorators are removed from their
  definitions. They remain importable (`app.list_artists`, …) so the existing
  unit tests that call them directly keep working.
- **`build_server(auth_cfg: AuthConfig | None) -> FastMCP`** is the single place a
  server is constructed:
  - `auth_cfg is None` → `FastMCP("tattoo-feed", instructions=...)` (no auth;
    stdio/local).
  - `auth_cfg is not None` → `FastMCP("tattoo-feed", instructions=...,
    auth=AuthSettings(...), token_verifier=IdpTokenVerifier(...))` — auth supplied
    via the **public constructor parameters**; the SDK's own auth↔verifier
    validation runs. **No private-attribute write anywhere.**
  - Registers the widget resource and all 11 tools on the instance (preserving
    `next_inspiration`'s `structured_output=False` + `meta=` options), then
    returns it.
- **No module-level `mcp` global.**
- **`main()`** resolves transport, then: HTTP → `build_server(load_auth_config())`
  + host/port + `run("streamable-http")`; stdio → `build_server(None).run()`. The
  `# pragma: no cover` shrinks to just the transport-dispatch / `run()` tail.

---

## 4. Approved dependencies

**None.** Phase 3 adds no dependencies. Anything that seems to need one → record
in `BLOCKERS.md` and stop.

---

## 5. The gate (identical to phases 1–2)

From the repo root, inside the dev container:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

All four exit 0. Coverage must stay **≥ 90%** (historically 100%) — and because
the auth wiring moves *out* from under the pragma, coverage honesty should
**improve**: `build_server`'s both branches (auth + no-auth) must be exercised by
tests, leaving only the genuinely un-runnable `run()` tail behind the pragma.

---

## 6. Chunks

### Chunk 0 — Baseline & contract lock (no `src/` change)
**Deliverables:**
- Confirm the gate is green on `refactor/auth` before any change.
- Verify against the installed `mcp` (1.27.2) that: (a) `FastMCP.__init__` accepts
  `auth=` and `token_verifier=` and validates the pair; (b) registering a tool via
  `server.tool()(fn)` is equivalent to the `@server.tool()` decorator (registers
  it and returns the function unchanged), and likewise for `server.resource(...)`.
- Capture the **parity contract** (the exact tool names the boot test expects; the
  401 / valid / 403 / metadata behaviours) in `PHASE3_RECONCILIATION.md`.

**Gate:** green (unchanged). **Success:** SDK equivalence confirmed in writing; no
`src/` change; gate exits 0.

### Chunk 1 — Factory + constructor-injected auth; retire the global & the private write
This is the atomic core. Removing the global and updating every referencer must
land together — any partial split leaves the gate red.

**Deliverables:**
- `server/app.py`: delete the module-level `mcp` global; drop the
  `@mcp.tool()` / `@mcp.resource()` decorators (tools/widget become plain
  module-level functions). Add `build_server(auth_cfg)` per §3, injecting auth via
  the constructor params. Rewrite `main()` to build via the factory and **remove
  `mcp._token_verifier = verifier` and `mcp.settings.auth = …`**; shrink the
  pragma to the `run()` tail.
- **Behavioural wiring test (hermetic)** driving the **real** factory:
  `build_server(auth_cfg)` → Starlette `TestClient` → tokenless `401`,
  valid-token admitted, under-scoped `403`, `/.well-known/oauth-protected-resource`
  `200`. In-test RSA keypair; JWKS mocked with `respx`; `RUN_LIVE` unset. (Replaces
  `test_server_auth.py`'s private `_make_auth_app` so the auth tests exercise
  production construction.)
- **Registration test:** `build_server(None)` registers the full tool set + the
  widget resource (covers what the old `app.mcp` introspection asserted).
- **Migrate referencers:** `test_server_widget.py` `app.mcp._resource_manager…` →
  `app.build_server(None)._resource_manager…`. `test_server_tools.py` /
  `test_image_rendering.py` should need **no change** (they call module-level
  functions + set `app._services`) — confirm, adjust minimally only if decorator
  removal affects them. `test_server_boot.py` spawns stdio and should pass
  unchanged.

**Gate:** all four exit 0; coverage ≥ 90% (target: hold 100%). **Success:** parity
contract from Chunk 0 holds; no private-attribute write remains
(`grep -n "_token_verifier" src` is clean); auth is configured only through
constructor params.

### Chunk 2 — Docs, REVIEW delta, close the seam
**Deliverables:**
- README: update any description of how the server is constructed / run.
- Write the phase-3 `REVIEW.md`: the human-only checks that remain (the **live
  OAuth login** and the **widget render in ChatGPT** are still verified by eye, not
  by the loop), plus how to confirm parity (tool set unchanged; stdio still boots;
  `curl …/mcp` → 401).
- Mark `scratchpads/auth-wiring-seam.md` **resolved**, noting how (factory +
  constructor params + behavioural test) and that the `# pragma` region shrank.
- Fix `scratchpads/phase-3-motivation.md`'s "branch name TBD" → `refactor/auth`.

**Gate:** green. **Success:** docs reflect the new construction; `REVIEW.md`
states exactly what a human must still verify; the seam doc is closed.

---

## 7. Non-goals (scope guard)

No new features, tools, transports, or dependencies. No change to tool behaviour
or descriptions. No `core` changes. No change to `server/auth.py`'s verification
logic (only *how* the verifier is attached). **Do not break stdio.** This is a
structural refactor with behaviour parity — nothing more.

---

## 8. Definition of done

Chunks 0–2 committed green on `refactor/auth`, one Conventional Commit each (e.g.
`refactor(server): build_server factory + constructor-injected auth  [chunk 1]`).
Behaviour parity proven by tests; no private-attribute auth write remains; the
`# pragma: no cover` region is just the `run()` tail; `REVIEW.md` lists the
human-only checks. Then **stop** — the live OAuth login and the in-ChatGPT widget
render are not declared verified by the loop. `main` is untouched; nothing is
force-pushed.
