# Phase 3 — how we got here, and what "done" means

The motivation and success criteria for the phase-3 refactor. This is the *why*
and the *definition of success* — **not** the design. The chunked design (its
`PLAN.md`, gate, and `REVIEW.md` delta) comes after this is agreed.

The deep technical anatomy of the problem lives in `scratchpads/auth-wiring-seam.md`;
this doc is the higher-altitude story: the decisions of phase 1, how phase 2's
requirements outgrew them, the issue that leaves us with, and what must be true for
phase 3 to be a success.

Grounding: `build_artifacts/Phase 1/Phase1_{CLAUDE,PLAN}.md`,
`build_artifacts/Phase 2/` (build logs + PROMPTS), the root governance docs, and
the `feat/remote-app` git history.

---

## Part 1 — Phase 1: the decisions, and why they were right *then*

Phase 1 built a **stdio** MCP server: an LLM client (Claude Desktop) browsing
Instagram tattoo-artist posts via Business Discovery. The decisions that matter
for this story:

- **Two-layer split.** `core` holds all logic and knows nothing about MCP;
  `server` is a thin FastMCP adapter (Phase1_CLAUDE §1). This was deliberately
  built so a future GUI could reuse `core` — and it has held up perfectly. **Phase
  3 does not touch it.**
- **A module-level `mcp = FastMCP(...)` singleton, with tools registered by
  `@mcp.tool()` decorators at import time.** This is the idiomatic FastMCP shape,
  and for phase 1 it was the *obviously correct* choice: there was nothing dynamic
  to feed the server object, so building it once at import and decorating tools
  onto it was the simplest thing that worked.
- **Explicit non-goals (Phase1_CLAUDE §9):** *"No GUI / web front-end of any kind
  (that is phase 2)"* and *"No multi-user accounts, auth flows, or OAuth handling
  beyond reading a token from the environment."* So phase 1 had **no HTTP, no
  auth, no runtime-derived configuration** the server object needed.

The key point: given phase-1 requirements, the import-time singleton had **no
downside.** There was no auth config, no environment-derived dependency, nothing
that had to be *injected* into the server at runtime. Building `mcp` at import and
hanging tools off it was correct, simple, and idiomatic. It was the right call for
what was being shipped.

---

## Part 2 — Phase 2: the requirements evolved

Phase 2's charter was to turn that stdio server into a **remote, OAuth-protected,
ChatGPT-renderable** app: an HTTP transport (chunk 1), an OAuth 2.1 resource
server (chunk 2, commit `2c7b9ed`), an Apps SDK widget (chunk 3), and a
containerised ngrok ingress (chunk 4). It was built with the automated-loop
machinery we then designed: a **shell-driven, one-chunk-per-fresh-`claude`-process
loop** (`build-loop.sh`), running **inside the docker dev image** (`run-loop.sh`),
hermetic gate per chunk.

This introduced something phase 1 never had: **a runtime, environment-derived
dependency that the server object itself needs.** OAuth config (issuer, JWKS URL,
audience, scopes) is read from the environment, and only exists when the process
actually starts — inside `main()`. The SDK's intended way to give the server that
config is **constructor parameters** (`FastMCP(..., auth=..., token_verifier=...)`).

And there's the collision:

- The auth config exists only **at run time** (in `main()`).
- But the `mcp` object is built at **import time** — because the phase-1 decorator
  pattern requires it to exist then.

So at the moment you *could* pass `auth=`/`token_verifier=` to the constructor, you
don't have them yet. Constructor injection is unavailable **given the import-time
singleton shape.** Phase 2 did the only thing that shape allows: it set the
verifier **after** construction, by hand, on a private attribute —
`mcp._token_verifier = verifier` — inside `main()`, under the one sanctioned
`# pragma: no cover`.

Crucially, **this was not a phase-2 mistake.** Phase-2 governance explicitly forbade
revisiting the structure: *"Touch only what a chunk names. No drive-by refactors"*
and *"`core` stays MCP-free."* Phase 2 was chartered to *add* auth, not to
*re-architect* how the server object is built. It honoured the phase-1 decisions
faithfully — and that faithfulness is exactly what produced the seam. The seam is
**phase-1 structure meeting a phase-2 requirement, with phase 2 not allowed to
change the structure.**

---

## Part 3 — The issue we now face

The result is the "auth-wiring seam" (full anatomy in `auth-wiring-seam.md`):

- **The auth wiring sits on unsupported API.** `_token_verifier` is private (the
  leading underscore = "internal, may change without notice"); there is no public
  setter, so the code reaches past the front door to attach the verifier.
- **It sits outside the gate.** The wiring lives inside `main()`, the one
  `# pragma: no cover` region, so no automated test exercises the real
  attachment. Its correctness currently rests on a human `curl` in `REVIEW.md`.

Two clarifications from our investigation, so phase 3 is motivated honestly rather
than by alarm:

1. **The risk is narrower than "imminent silent bug."** We tested it: `mcp` ships
   type information, and `mypy --strict` (which the gate runs over `main()` — the
   pragma hides it from *coverage*, not from *mypy*) **does** flag a *renamed or
   removed* `_token_verifier`. So a straight rename would turn the gate red. The
   genuinely silent case is narrower: a **semantic** change (the SDK keeps the
   attribute name but stops reading it, or wires auth at construction instead of at
   `run()`). Only a **behavioural test** catches that.
2. **So the real case for phase 3 is structural, not a fire.** The import-time
   singleton was a phase-1 convenience that no longer serves the shipped
   requirements. Phase 2 added a runtime dependency the structure can't cleanly
   accept, and we are now *protecting that legacy decision* with a private-attribute
   workaround. The architecture should serve what we ship today — an authenticated
   public endpoint with a retained local stdio mode — not preserve a structure
   whose original justification (stdio-only, no auth) is gone.

That is the thesis: **fix the structural cause, don't keep papering the symptom.**

---

## Part 4 — What must be true for phase 3 to be a success

Phase 3 is a **refactor**: same external behaviour, better structure. Success is
defined by invariants preserved + structural goals met + process discipline +
honest scope.

### 4.1 Behaviour that must be preserved (parity — non-negotiable)
- **stdio local optionality is retained**: the server still runs over stdio,
  **unauthenticated**, for local development. Auth is never made mandatory.
- **HTTP runs authenticated**: the public endpoint still rejects an unauthenticated
  request with `401` before any tool runs (governance §8).
- **The MCP surface is unchanged**: all 11 tools + the inspiration widget resource,
  identical names, descriptions, and behaviour. No tool is added, removed, or
  altered.
- **`core` stays MCP-free.** The two-layer split is untouched.

### 4.2 Structural goals (the actual point)
- Auth is supplied through the **public constructor parameters**
  (`auth=` / `token_verifier=`) — **no private-attribute write.**
- A **factory** — `build_server(auth_cfg: AuthConfig | None) -> FastMCP` — builds
  the server with auth when configured and without it (stdio) when not. Tools are
  registered inside it.
- The **auth decision is made at run, beside the transport decision** (auth only on
  the HTTP path), preserving the coupling the shipped design wanted — now without
  the workaround.
- `main()`'s `# pragma: no cover` **shrinks toward just `mcp.run(...)`** — the only
  genuinely un-testable line — restoring the pragma to its original honest scope.

### 4.3 Test & quality goals
- A **behavioural wiring test** exercises the *real* factory path hermetically:
  tokenless → `401`, valid token → admitted, under-scoped → `403` (using an
  in-test keypair + mocked JWKS, no live network). This is the guard that also
  covers the *semantic*-change risk types can't see.
- The **hermetic gate stays green**: `ruff format --check`, `ruff check`,
  `mypy --strict src`, `pytest … --cov-fail-under=90`. Coverage honesty should
  *improve* (less wiring hidden under the pragma), not regress.

### 4.4 Process goals — same loop principles as phase 2
- Built with the **shell-driven, one-chunk-per-fresh-`claude`-process loop**
  (`build-loop.sh` lineage), **inside the docker dev image** (`run-loop.sh`), fresh
  context per chunk, state crossing chunk boundaries only via git commits +
  `BLOCKERS.md`.
- **One Conventional Commit per passed chunk**, on a **phase-3 branch** (name TBD in
  the plan); **never on `main`**, never force-push.
- The same anti-cheat rules carry over: never weaken a test or tooling to go green;
  never a live network call in the test path; never commit secrets. A chunk that
  can't pass honestly after 3 attempts → stop, write `BLOCKERS.md`.
- No production secrets in the build container (the gate is hermetic).

### 4.5 Definition of done
- Every phase-3 chunk committed green; behaviour parity proven by tests; the
  `auth-wiring-seam.md` fragilities closed (public API + tested wiring + shrunk
  pragma).
- `REVIEW.md` refreshed with the human-only checks that remain — the **live OAuth
  login** and **widget render in ChatGPT** still need human eyes and are *not*
  declared verified by the loop.

### 4.6 Explicit non-goals (scope guard)
- No new features, tools, or transports. No change to tool behaviour or
  descriptions. No `core` changes. No new dependencies unless a chunk demonstrably
  needs one (record + stop otherwise). **Do not break stdio.** This is a structural
  refactor with behaviour parity — nothing more.

---

## One-paragraph summary

Phase 1 chose a module-level `FastMCP` singleton with import-time `@mcp.tool`
decorators — correct and downside-free for a stdio-only server with no auth. Phase
2 added a remote OAuth-protected HTTP endpoint, which introduced a runtime,
env-derived dependency the server now needs — but the import-time singleton means
`mcp` is built before that config exists, so constructor injection was impossible
and phase 2 (correctly barred from re-architecting) fell back to a private
`mcp._token_verifier = verifier` write inside the pragma'd `main()`. That seam puts
the auth wiring on unsupported API and outside the gate; our testing showed the
*rename* risk is actually caught by mypy, leaving a narrower *semantic* silent risk
that only a behavioural test closes. Phase 3 is the sanctioned structural fix: a
run-time `build_server(auth_cfg)` factory using the public constructor parameters,
retaining unauthenticated stdio as a first-class local mode, proven by a hermetic
tokenless→401 wiring test, with `main()`'s pragma shrunk to just `mcp.run()` —
built with the same docker + shell-loop discipline as phase 2. Success = identical
behaviour, supported-API wiring, the seam closed, and stdio intact.
