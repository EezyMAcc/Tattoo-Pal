# Removing the global — the phase-3 decision, from scratch

Why phase 3 deletes the module-level `mcp` object, what a "global" even is, and —
concretely — which tests change and which don't. Written for a first encounter
with the term "global."

Companion docs: `auth-wiring-seam.md` (the problem this fixes),
`phase-3-motivation.md` (the why + success criteria), root `PLAN.md` (the chunks).

---

## Part 1 — What a "global" even is

Start with where names live in Python. A variable is just a **name bound to a
value**, and *where* you write that binding decides *who can see it*.

- A **local** name is created **inside a function** and exists only while that
  function runs. When the function returns, the name is gone.
- A **global** (more precisely, a *module-level*) name is created at the **top
  level of a `.py` file** — not inside any function. It exists for the whole life
  of the program, every function in that file can see it, and **other files can
  import it.**

The analogy: a local variable is a **sticky note on someone's desk inside a closed
office** — it exists only while that person is working in that room, and nobody
outside sees it. A global is the **noticeboard in the building lobby** — it's
there all day, everyone in the building can read or change it, and visitors from
other buildings (other modules) can walk in and read it too.

```python
TITLE = "tattoo-feed"     # module-level (global): visible everywhere, importable

def greet():
    name = "Rex"          # local: exists only while greet() runs
    return f"{TITLE} / {name}"
```

`TITLE` is on the lobby noticeboard; `name` is a sticky note that's thrown away
when `greet()` finishes.

**The fact that matters most: module-level code runs at *import*.** When Python
first imports a file, it executes every top-level line, top to bottom, *right
then*. So a global isn't created "when you call something" — it's created the
instant the module is imported. Hold that; it's the whole story.

---

## Part 2 — The global in *this* app, and why it's the problem

`server/app.py` has this at the top level:

```python
mcp = FastMCP("tattoo-feed", instructions=...)     # ← a module-level global

@mcp.tool()
def list_artists() -> list[Artist]: ...
```

`mcp` is a global — a constructed `FastMCP` object on the lobby noticeboard. Why
does it exist as a global at all? Because of the line under it. `@mcp.tool()` is a
**decorator**, and decorators are top-level lines that **run at import** (Part 1).
For `@mcp.tool()` to run, `mcp` must already exist at import. So the pattern
*forces* `mcp` to be a global, built at import time, before anything else happens.

That is the root of the auth-wiring seam (`auth-wiring-seam.md`). OAuth config
isn't known until the program *runs* (it's read from the environment inside
`main()`). But `mcp` was already built at import — before that config existed — so
phase 2 couldn't pass auth into its constructor and had to bolt it on afterward
with the private `mcp._token_verifier = verifier` write. **The global being born
too early is exactly what made clean auth wiring impossible.**

---

## Part 3 — The decision: remove the global (and what that does *not* mean)

Phase 3 deletes the module-level `mcp` object and builds the server **on demand,
inside a function** instead:

```python
def build_server(auth_cfg: AuthConfig | None) -> FastMCP:
    mcp = FastMCP("tattoo-feed", instructions=..., **auth_kwargs(auth_cfg))
    mcp.tool()(list_artists)          # register the tools on this instance
    ...
    return mcp
```

Now the server is built **when `main()` calls `build_server(...)`**, *after* the
auth config exists — so auth goes in through the public constructor parameters, no
private write needed. The "born too early" problem is gone because nothing is born
at import anymore.

**The crucial subtlety (this trips people up):** "remove the global" means remove
the module-level *`FastMCP` object*. It does **not** mean move everything inside
functions. The **tool functions stay defined at module level** — they're just
ordinary `def`s now, no longer decorated:

```python
def list_artists() -> list[Artist]:          # still module-level, still importable
    return _get_services().artists.list_artists()
```

So there are two different module-level things, and we treat them differently:

| Module-level thing | Phase 3 |
|---|---|
| `mcp = FastMCP(...)` — a constructed **object** global | **removed** (built in the factory instead) |
| `def list_artists(...)` — a **function definition** | **kept** at module level; registered inside the factory |

Keeping the function definitions is what lets the existing unit tests keep calling
`app.list_artists()` directly. Removing only the constructed-object global is what
fixes the seam. Distinguishing these two is the entire trick.

**Why remove rather than keep a no-auth global?** We considered keeping
`mcp = build_server(None)` as a convenience. We're removing it instead because the
whole point of phase 3 is that the architecture serves the shipped requirements,
not a leftover stdio-only-era convenience. A lingering global re-introduces the
"object built at import" shape we're trying to retire, and invites the next person
to hang something off it again. One construction path — the factory — is the
honest end state.

---

## Part 4 — What this means for the tests (findings)

I read every test that touches `server/app.py`. They split cleanly into "no change"
and "must change," and the dividing line is exactly the Part 3 distinction —
*do they use the global **object**, or do they use module-level **functions**?*

### No change needed — they call module-level *functions*
- **`test_server_tools.py`** — calls the tools directly (`app.list_artists()`,
  `app.add_artist("@Bob")`, `app.next_inspiration()`, …) and injects fakes by
  setting `app._services`. Because the tool **functions stay module-level** (Part
  3) and `_services` / `_get_services` are untouched, these tests work verbatim.
- **`test_image_rendering.py`** — same pattern (`app.next_inspiration()`, sets
  `app._services`). No change.
- **`test_server_transport.py`** — imports `resolve_transport`, which stays a
  module-level function. No change.
- **`test_server_boot.py`** — launches `python -m tattoo_feed.server.app` as a
  **subprocess** over stdio and lists tools. It never imports the `mcp` global; it
  exercises `main()` end-to-end. As long as `main()`'s stdio path builds a server
  with all tools (it will, via `build_server(None)`), this passes unchanged. It is
  in effect a free parity check.

### Must change — they use the global *object* `app.mcp`
- **`test_server_widget.py`** — uses `app.mcp._resource_manager.list_resources()`
  in **4 places** to assert the widget resource is registered. `app.mcp` no longer
  exists, so each must build an instance first:
  `app.build_server(None)._resource_manager.list_resources()`. Mechanical, but
  required, and it's authorised by `PLAN.md` Chunk 1.

### Must change — it duplicates what the factory will now do
- **`test_server_auth.py`** — has a private helper `_make_auth_app(verifier)` that
  hand-builds a `FastMCP` with auth and tests `401` / valid / `403` / metadata via
  Starlette's `TestClient`. This is essentially a *prototype of `build_server`*.
  Phase 3 repoints those assertions at the **real** `build_server(auth_cfg)` (with
  the in-test keypair + `respx`-mocked JWKS), so the auth tests now exercise
  production construction instead of a test-only twin. The verification *unit*
  tests for `IdpTokenVerifier` are unaffected (that logic doesn't change).

### Unaffected entirely
`test_config.py`, `test_errors.py`, `test_models.py`, `test_repositories.py`,
`test_graph_client.py`, `test_imaging.py`, `test_services.py`, `test_smoke.py` —
none touch `server/app.py`'s construction.

**The pattern to remember:** a test breaks **only if it reached for the global
object `app.mcp`** (or for the SDK app that the global produced). A test that
reached for a module-level **function** is fine, because those stay. That single
distinction predicts every change in the list above.

---

## One-paragraph summary

A "global" is a name defined at a file's top level — created at *import*, visible
to the whole module, and importable elsewhere (the lobby noticeboard, vs. a
function's throwaway sticky note). This app's `mcp = FastMCP(...)` is such a
global, forced to exist at import because the `@mcp.tool()` decorators run at
import and need it — and being built that early, before the runtime OAuth config
exists, is the root cause of the auth-wiring seam. Phase 3 removes the
constructed-object global and builds the server on demand in a `build_server`
factory, so auth goes in via the public constructor params. Crucially, "remove the
global" means remove the *object*, not the *function definitions* — the tool `def`s
stay at module level and are registered inside the factory. That distinction is
also what predicts the test impact: tests that call module-level functions
(`test_server_tools`, `test_image_rendering`, `test_server_transport`,
`test_server_boot`) need no change; the only ones that change are those that
reached for the `app.mcp` object (`test_server_widget` → `build_server(None)`) or
that prototyped the factory (`test_server_auth`'s `_make_auth_app` → real
`build_server`).
