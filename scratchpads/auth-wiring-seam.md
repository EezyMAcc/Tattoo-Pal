# The auth-wiring seam — two coupled fragilities in `server/app.py`

> **STATUS: RESOLVED (2026-06-17, branch `refactor/auth`)** — The two structural
> fragilities documented in Parts 1–3 were closed by the phase-3 refactor:
>
> 1. **Private-attribute write (Part 1):** `mcp._token_verifier = verifier` is gone.
>    Auth is configured exclusively through `FastMCP`'s public `auth=` /
>    `token_verifier=` constructor parameters inside `build_server(auth_cfg)`.
>    The SDK's own pair-validation fires at construction; `mypy --strict` sees the
>    typed boundary.
>
> 2. **Pragma blind spot (Part 2):** The `# pragma: no cover` region shrank to
>    just the `mcp.run()` / transport-dispatch tail. The auth wiring is covered by
>    a hermetic behavioural test (`tests/test_server_auth.py`) that drives
>    `build_server(auth_cfg)` through a Starlette `TestClient` and asserts:
>    tokenless → `401`, valid token admitted, wrong scope → `403`, metadata
>    endpoint → `200`. This guards against both attribute-rename and
>    semantic-change risks.
>
> **Still open:** Bug 2 (`421 Invalid Host header`, Part 4) is **not** resolved
> by phase 3. The SDK bakes `settings.transport_security` at `FastMCP` construction
> time; the `server.settings.host` override in `main()` does not update it. See
> Part 4 for the diagnosis and the two fix options.

A from-first-principles reference for two things in the phase-2 server that look
small but sit on top of a fair amount of hidden machinery:

1. `app.py` sets `mcp._token_verifier = verifier` — it writes a *private* SDK
   attribute by hand instead of using a constructor parameter.
2. The whole block that does that wiring lives inside `main()`, which carries
   `# pragma: no cover`, so **no test ever runs it.**

Neither is a bug. Both are deliberate consequences of how the server is shaped.
But they reinforce each other in a way worth understanding before the review
signs off on the auth path. This doc builds up the background first, then takes
each one apart, then shows how they connect and what the cheap fix is.

Grounded in the installed SDK (`mcp==1.27.2`) — every SDK claim below was read
out of the actual package, not recalled. The history in **Part 0.5** is grounded
in the build artifacts: `build_artifacts/Phase 1/` (the phase-1 governance that
*originated* the testing rules), `build_artifacts/Phase 2/` (the build logs,
including the abandoned one-window run), and the `feat/remote-app` git history.

> **▶ MORNING PICKUP (2026-06-16).** This seam has now fired **twice** in live
> testing. One bug is fixed; one is open and is your next concrete task. Skip to
> **Part 4 — Field log** at the bottom: it has the current state (auth works; a
> `421 Invalid Host header` is the only remaining blocker), the exact cause, and
> the precise fix to apply. Parts 0–3 are the background theory if you want it.

---

## Part 0 — background you need first

If the concepts below are already familiar, skip to Part 1. The two fragilities
only make sense once these four things are clear.

### 0.1 What FastMCP is, and what "the server object" is

`FastMCP` is the class from the MCP Python SDK that turns plain Python functions
into tools an AI client (here, ChatGPT) can call over a network. You make **one
instance** of it and then decorate functions:

```python
mcp = FastMCP("tattoo-feed", instructions=...)   # the server object

@mcp.tool()
def list_artists() -> list[Artist]: ...
```

The `@mcp.tool()` decorator runs **at import time** — the moment Python reads the
file, top to bottom, it executes those decorator lines and registers each
function on that one `mcp` object. So `mcp` has to already exist as a
module-level global by the time the decorators run. This is why there is a single
`mcp = FastMCP(...)` near the top of the file and everything hangs off it. Hold
onto this fact; it is the root cause of fragility #1.

### 0.2 "Credential-free import" — why the module must load with no secrets

Importing `server/app.py` must not require an Instagram token, an identity
provider, or any network access. Two reasons:

- The stdio entry point and the test suite both `import` this module just to see
  the list of tools. Listing tools should never need live credentials.
- The hermetic-test rule (CLAUDE.md §1.3) forbids live network calls in the test
  path. If importing the module reached out to an IdP, every test would violate
  that.

The code honours this by building the real services **lazily** — only on the
first actual tool call (`_get_services()` / `_build_services()`), never at
import. The same principle applies to auth: at import time we have no idea what
identity provider we'll point at, because that comes from `MCP_AUTH_*`
environment variables read at *runtime*, inside `main()`.

So: **the `mcp` object is born at import, ignorant of auth; the auth config only
exists later, at run.** That gap is the whole story.

### 0.3 What a "resource server" and a "token verifier" actually do

Phase 2 makes the server an OAuth 2.1 **resource server**. In OAuth terms there
are three parties:

- the **client** (ChatGPT) that wants to call your tools,
- the **identity provider / authorization server** (Auth0, Okta, etc.) that logs
  the user in and hands the client a signed **access token** (a JWT),
- your **resource server** (this MCP server) that must *check* the token on every
  request before letting the call through.

Your server never logs anyone in. It only **verifies** tokens that someone else
issued. The thing that does that verification is the **token verifier**: given
the raw JWT string from the `Authorization: Bearer ...` header, it returns either
an `AccessToken` object (valid) or `None` (reject → the SDK turns that into a
`401`). In this codebase that verifier is `IdpTokenVerifier` in
`server/auth.py`, and its `verify_token` checks the JWT's signature (against the
IdP's published keys), its issuer, its audience, and its expiry.

### 0.4 Where the verifier plugs into a request — middleware, from scratch

This is the section that makes fragility #1 click, so we'll build it from the
ground up. Everything below was read out of the installed SDK
(`mcp==1.27.2`, `mcp/server/fastmcp/server.py`); line numbers are from that file.

#### 0.4.1 What "middleware" even means

Start with the bare picture. An HTTP request is just data arriving over the
network: a line like `POST /mcp` plus some headers (one of which is
`Authorization: Bearer <jwt>`). Somewhere at the far end, one of *your* functions
has to run — here, the code that executes the MCP tool — and hand back a response.

The question middleware answers is: **what runs in between?** Between "a request
arrived" and "your tool runs," you almost always want some general-purpose steps —
check the caller is who they say they are, reject them if not, log the request,
and so on — that you do *not* want to copy-paste into every single tool.
Middleware is how you factor those steps out.

The mental model that makes it stick: **airport security.** Your tool is the
departure gate. Before a passenger (the request) reaches the gate, they pass
through a fixed sequence of checkpoints — boarding-pass scan, ID check, security
screening. Each checkpoint can do one of three things:

- **annotate** you and wave you on ("verified passenger — proceed"),
- **pass** you to the next checkpoint unchanged, or
- **stop** you and send you back ("no boarding pass — denied").

Only a passenger who clears *every* checkpoint reaches the gate. In code it's
exactly this, expressed as **nested wrappers** (think Russian dolls). The outermost
wrapper receives the raw request first; it does its bit, then calls the next
wrapper inside it; that one calls the next; the innermost is your actual handler.
The response then bubbles back out through the same layers. Each layer is, itself,
just "a thing that takes a request and produces a response" (the technical name is
an *ASGI app*) — and a piece of middleware is simply one of those that *wraps
another one*. That's the whole concept: **middleware is a layer you wrap around
your app to intercept every request before it reaches your handler.**

#### 0.4.2 The actual middleware stack in *this* server

Now anchor it. When `main()` calls `mcp.run(transport="streamable-http")`, the SDK
ends up calling `streamable_http_app()` (server.py:950). That function **builds**
the layered app described above — a Starlette app assembled from a list of
middleware plus the routes — and *that* assembled object is what listens for HTTP
requests. (Important: this build happens **at run time**, not when the module is
imported. Hold that thought for 0.4.3.)

For an auth-configured server, the stack it builds, from **outermost (hits the
request first) to innermost (your tool)**, is:

1. **`AuthenticationMiddleware`** — configured with
   `backend=BearerAuthBackend(self._token_verifier)` (server.py:980–983). This is
   the *"who are you?"* checkpoint. It pulls the `Authorization: Bearer <jwt>`
   header off the request, hands the raw token to **your** verifier — the
   `IdpTokenVerifier.verify_token` from 0.3 — and records the outcome on the
   request: either "authenticated as this subject, with these scopes" or
   "anonymous." Crucially, **it does not reject anyone.** Its only job is to
   *establish identity* (this is what "authentication" means). A request with a
   bad token simply comes out the other side marked "anonymous."

2. **`AuthContextMiddleware`** — plumbing: it stashes that identity in a
   context variable so code deeper in can ask "who's calling?" without it being
   threaded through every function call. You can mostly ignore it.

3. **`RequireAuthMiddleware`**, wrapping the actual MCP endpoint
   (server.py:1014). This is the *"are you allowed in?"* checkpoint — and **this
   is the one that rejects.** If the request came through Layer 1 as anonymous, or
   is missing a `required_scopes` scope, `RequireAuthMiddleware` stops it here and
   returns **`401 Unauthorized`** (with a `WWW-Authenticate` header pointing at the
   `/.well-known/oauth-protected-resource` metadata document — itself added at
   server.py:1025–1035) or **`403 Forbidden`**. Only a request that clears this
   layer reaches the innermost `streamable_http_app`, which finally runs your tool.

So the two jobs you might lump together as "auth" are actually **two separate
layers**: Layer 1 *authenticates* (figures out who you are; never rejects), and
Layer 3 *authorizes / enforces* (admits or rejects). This split is the concrete
reason Part 1 insists that **both** halves get set — `settings.auth` (which carries
`required_scopes` and is what turns the whole block on, server.py:978) feeds the
enforcement layer, and `_token_verifier` feeds the identification layer. Set only
one and you get a half-built, broken stack.

#### 0.4.3 Why this is the hook for fragility #1

Here's the payoff. That entire stack is **conditional**, and — read the real
branch — both the identify layer *and* the enforce layer hinge on the same single
attribute, `self._token_verifier`:

```python
# inside streamable_http_app(), condensed from server.py:978–1022
if self.settings.auth:                      # 978  build the auth middleware at all?
    if self._token_verifier:                # 980  ↳ attach the Bearer identify-backend
        middleware = [
            Middleware(AuthenticationMiddleware,
                       backend=BearerAuthBackend(self._token_verifier)),
            Middleware(AuthContextMiddleware),
        ]

if self._token_verifier:                    # 1002 wrap the route in the enforce-gate?
    routes.append(Route(path,
        endpoint=RequireAuthMiddleware(streamable_http_app, required_scopes, ...)))
else:
    # "Auth is disabled, no wrapper needed"
    routes.append(Route(path, endpoint=streamable_http_app))   # ← bare tool, NO gate
```

Now replay fragility #1 through this. Our code attaches the verifier by hand:
`mcp._token_verifier = verifier` (Part 1). Suppose a future SDK release renames
that attribute, or starts building this app **at construction time** instead of at
`run()` — so our later assignment lands on something the SDK no longer reads. At
`run()`, `self._token_verifier` is then falsy, and trace what the code above does:

- The inner `if` at 980 is false → **Layers 1 and 2 are never built.** No token is
  ever parsed off any request.
- The `if` at 1002 is false → the route takes the **`else`** branch → its endpoint
  is the **bare** `streamable_http_app`, with **no `RequireAuthMiddleware`**.
  Nothing checks for a token.

Result: the server boots cleanly and serves **every** request — no token required —
straight through to your tools. And here's the sting: **no error is raised and
nothing looks wrong**, because that `else` branch is a completely *normal,
supported* path. It is exactly how the server legitimately runs unauthenticated in
stdio/local-dev mode. The code literally cannot distinguish *"the operator chose no
auth"* from *"auth silently fell off the object."* Both produce the same happy,
wide-open server.

That is precisely why Part 1 calls the failure **silent**: the bad outcome isn't a
crash you'd notice — it's the quiet selection of the unauthenticated branch. Two
properties make it nasty, and both are visible above:

- **It's read lazily, at `run()` time** (the stack is built inside
  `streamable_http_app()`, reached only via `mcp.run(...)`). Nothing between our
  assignment and `run()` re-checks it, so there's no earlier moment to catch a
  mistake.
- **The whole auth stack — identification *and* enforcement — switches on the
  truthiness of that one private attribute.** Lose the attribute, lose *all* of
  it, at once, quietly. And `mypy --strict` can't help (Part 1.4 / Part 2): it
  never executes `run()`, and assigning any attribute to an object is legal Python.

So the single sentence to carry forward is: **the verifier is read lazily, at
`run()` time, from a private attribute named `_token_verifier`, and that one
attribute is the on/off switch for the entire auth stack — which is why a silent
loss of it doesn't degrade auth, it deletes auth.**

---

## Part 0.5 — Provenance: how this seam actually came to exist

Neither fragility was introduced in one careless commit. Both are a **phase-1
rule meeting a phase-2 reality** — worth knowing before you "fix" them this
morning, because the rules they descend from are still load-bearing and the right
move is to restore their original scope, not abolish them.

### 0.5.1 The pragma rule is inherited — and was written for a *stdio launcher*

The "exactly one `# pragma: no cover`, on `main()`" rule did not originate in
phase 2. It is verbatim phase-1 governance:

- `Phase1_CLAUDE.md` §2.5: *"Never weaken coverage by adding blanket
  `# pragma: no cover`. **The only permitted pragma is on the stdio entrypoint
  `main()` in `server/app.py`.**"*
- `Phase1_PLAN.md` §2: *"Only `server/app.py:main()` may carry
  `# pragma: no cover`."*

Read the wording: *"the **stdio entrypoint** `main()`."* In phase 1 that is
exactly what `main()` was — the thin launcher from phase-1 Chunk 6 whose whole job
was to start the server over stdio. Excluding a one-purpose stdio launcher from
coverage costs almost nothing: there is no logic in it to hide.

Phase 2 carried that rule forward **unchanged** (current `CLAUDE.md` §4 repeats it
almost word for word) while progressively changing *what lives inside `main()`*,
chunk by chunk on `feat/remote-app`:

- **Chunk 1** (`7062a6a`) added the HTTP transport branch (host/port,
  streamable-http).
- **Chunk 2** (`2c7b9ed`) added the auth wiring — `settings.auth`,
  `_token_verifier`, the verifier construction.
- **Chunk 4** (`1257947`) added the containerised public-bind path — and live
  testing later surfaced the transport-security/host question (Bug 2, Part 4).

So the pragma stayed scoped for a *stdio entrypoint* while `main()` quietly became
the **HTTP + auth + transport-security wiring hub.** The blind spot in Part 2 is
not a rule someone broke; it's a rule that **outlived the shape it was written
for.** That is precisely why Part 3's fix is *shrink the pragma back to just the
genuine launcher (`mcp.run`)* — restoring the rule to its original, defensible
scope rather than removing it.

### 0.5.2 The hermetic-test rule is why the tail genuinely can't be covered

Part 2.4's claim that `mcp.run()`'s tail can't be unit-tested also traces to
inherited governance, not a phase-2 shortcut:

- `Phase1_CLAUDE.md` §2.3: *"**Never make a live network call in the test path.**
  All HTTP to Instagram is mocked with `respx`. The one real integration test is
  gated behind `RUN_LIVE=1` and must never be run by you."*

Phase 2 kept this exactly (`CLAUDE.md` §1.3, §4). Starting a real HTTP server
against a live IdP is the very live-network thing the hermetic rule forbids in the
test path — so the `REVIEW.md` manual `curl` is the **compensating control the
hermetic rule itself implies.** "Correctness rests on a human eyeballing a `curl`"
is not a criticism of someone's choice; it is the *designed* consequence of a
discipline the project deliberately inherited.

### 0.5.3 The private-attribute write was a fork — a sibling build took the other road

The most concrete piece of provenance: **the same governance, run two different
ways, produced two different auth wirings.**

- The **shell-loop** build — the one that shipped (Chunk 2, `2c7b9ed`) — wired
  auth in `main()` at runtime via the private `mcp._token_verifier = verifier`
  write. This is the code Part 1 dissects.
- An **earlier one-window `/loop`** build
  (`build_artifacts/Phase 2/identified_loop_one_window_…txt` — the
  single-growing-context attempt that `build-loop.sh` was later created to
  replace) wired auth through the **public constructor**: a `_auth_kwargs()`
  helper returning `{"auth": …, "token_verifier": …}`, splatted into
  `FastMCP(…, **_auth_kwargs())` at module import. Both honour credential-free
  import — the helper returns `{}` when no IdP env is set, so import touches no
  creds and no network.

The contrast matters for two reasons:

1. **It proves the constructor path was reachable.** Part 1.5 lists factory /
   constructor injection as an alternative; it isn't hypothetical — a sibling
   autonomous run actually did it. And the constructor form **keeps the SDK's
   validation block** (Part 1.1.2 / 1.4) that the shipped private-write skips:
   passing `auth=` and `token_verifier=` together is exactly what those guard
   rails check.
2. **It shows this is a genuine design fork, not an oversight.** Two honest builds
   from one set of docs diverged precisely here — strong evidence that the seam is
   a real decision point deserving Part 3's deliberate treatment, not a slip to
   paper over.

The shipped `main()` form does buy one thing the constructor form gives up: it
resolves the auth-on decision **at run, beside the transport decision** (auth only
in the HTTP branch) rather than freezing it at import. That is the tradeoff — and
it is the tradeoff that *forced* the private write, because by the time `main()`
runs, the module-level `mcp` object (0.1) already exists and the constructor door
has closed.

> **Bottom line for this morning:** the Part 3 `configure_http()` extraction is
> not just a tidy-up — it reconciles all three threads above. It moves the wiring
> out from under a pragma that was only ever meant for a stdio launcher (0.5.1),
> keeps `mcp.run`'s genuinely-untestable tail behind the hermetic line (0.5.2),
> and recovers the constructor-style validation a sibling build showed was
> achievable (0.5.3) — without giving up the run-time auth/transport coupling the
> shipped design chose.

---

## Part 1 — `mcp._token_verifier = verifier`: writing a private attribute

### 1.0 What "writing a private attribute" even means — from scratch

Before *why* it's fragile, get clear on *what the line does*. It rests on one
fact about Python that surprises people coming from Java/C#.

**An attribute is a named slot on an object.** Picture an object as a box of
labelled slots. `mcp.settings` reads the slot named `settings`; the line
`mcp._token_verifier = verifier` puts the bouncer (the *verifier* — the thing that
*checks* tokens, not a token itself) into the slot named `_token_verifier`.

**Python lets you set *any* slot, with no check.** Assigning an attribute never has
to be "declared" first, and for a plain object Python doesn't ask whether it's a
slot the class actually uses:

```python
class Dog:
    def __init__(self):
        self.name = "Rex"

d = Dog()
d.collar = "red"   # ✅ creates a brand-new slot, no error
d.nmae = "Fido"    # ✅ a TYPO — also no error; sets a *different*, useless slot
print(d.name)      # → "Rex"   (the real slot is untouched)
```

That `d.nmae` typo *is* the whole mechanism in miniature: a wrong name doesn't
crash — it quietly sets a slot nobody reads. Hold onto it; 1.4 is exactly this
typo, except committed by someone *else* (a future SDK) in slow motion.

**The leading underscore is a sign, not a lock.** The `_` on `_token_verifier` is
Python's universal convention for *"internal; not public API; may change without
notice."* But it is only a **"STAFF ONLY" sign on an unlocked door** — Python won't
stop you walking in. Names *without* the underscore (`mcp.settings`) are the
public, promised-stable API; underscore names carry no such promise.

**"No public setter" = no polite way in.** The blessed way to hand over the
verifier is the constructor parameter (1.1) — but `mcp` is already built (1.2), and
the SDK exposes *no* public method to attach a verifier afterwards. So the code
can't knock on the front door; it walks into the staff room and sets the private
slot by hand. That is what "reaching past the front door" means — and it is the
root of everything in 1.4.

### 1.1 The API the SDK intends you to use

`FastMCP.__init__` accepts auth as **constructor parameters** (confirmed from the
installed signature):

```python
FastMCP(
    "tattoo-feed",
    auth=AuthSettings(...),          # the policy: issuer, audience, scopes
    token_verifier=IdpTokenVerifier(...),  # the thing that checks tokens
)
```

When you pass them, the constructor does three things, in order (read from the
SDK source):

1. stores the policy: `self.settings.auth = auth`
2. **validates the combination** — it raises `ValueError` if you give `auth`
   without a verifier, or a verifier without `auth`, or two conflicting
   verifiers. These are guard rails against a half-configured server.
3. stores the verifier: `self._token_verifier = token_verifier`

Later, at `run()`, step 0.4's middleware reads `self._token_verifier`. So the
intended lifecycle is: **construct with auth → validated → stored → consumed at
run.**

### 1.2 Why this codebase cannot use that path

Go back to 0.1 and 0.2. The `mcp` object is created at **import time**, before
any auth config exists, because the `@mcp.tool()` decorators need it to exist
then. At that moment we cannot pass `auth=`/`token_verifier=` — we don't have
them yet. They only materialise later inside `main()`, after reading
`MCP_AUTH_*` from the environment.

So the constructor-injection API is simply unavailable given this shape. The code
does the only thing left: it sets, *after* construction, the exact two attributes
the constructor would have set:

```python
# app.py, inside main(), HTTP + auth-configured branch
mcp.settings.auth = AuthSettings(
    issuer_url=AnyHttpUrl(auth_cfg.issuer),
    resource_server_url=AnyHttpUrl(auth_cfg.audience),
    required_scopes=auth_cfg.required_scopes or None,
)
mcp._token_verifier = verifier
```

### 1.3 Why this is *correct today*

It works for one specific reason: **the verifier is read lazily.** Nothing looks
at `_token_verifier` between construction and `run()`. By the time `mcp.run(...)`
builds the HTTP app and reads the attribute (0.4), our assignment has already
happened. The two halves we set — `settings.auth` (the policy) and
`_token_verifier` (the checker) — are precisely the two the middleware needs, and
they're consistent with each other. So the running server authenticates exactly
as if we'd passed them to the constructor.

### 1.4 Why it is fragile anyway

Three distinct reasons, in increasing order of how much they should bother you:

- **`settings.auth` is a public-ish field; `_token_verifier` is not.**
  `settings.auth` is a declared field on a settings model — assigning it is
  reasonable. But the leading underscore on `_token_verifier` is Python's
  universal convention for *"internal; not part of the public API; may change
  without notice."* There is **no public setter** for it — the SDK only expects
  it to be set by the constructor. We are reaching past the front door.

- **The breakage would be silent — but only for *some* kinds of change
  (corrected 2026-06-17 by testing the installed SDK).** The failure shape is the
  `d.nmae` typo from 1.0: if the slot we *write* stops matching the slot the SDK
  *reads*, our line keeps running without error, sets a dead slot, and the server
  boots **unauthenticated** — every tool exposed with no token check. The question
  is whether anything catches that mismatch. The original draft of this doc said
  "mypy is blind to it." **That was wrong.** Tested: `mcp` ships type information,
  and `mypy --strict` *does* flag assignment to an attribute `FastMCP` doesn't
  have —

  ```text
  error: "FastMCP[Any]" has no attribute "_gone"  [attr-defined]
  ```

  The gate runs `mypy --strict src`, and the `# pragma: no cover` hides `main()`
  from *coverage*, not from *mypy* — so mypy genuinely analyses this line.
  Therefore a future SDK that **renames or removes** `_token_verifier` would turn
  the **gate red, loudly,** before anything shipped.

  The genuinely *silent* failures are the narrower set where the attribute **still
  exists** (so mypy stays happy) but its *meaning* changed underneath us: the SDK
  keeps `_token_verifier` yet **stops reading it** (deprecates it), or starts
  **building the auth app at construction** instead of at `run()` so our later
  assignment is ignored. Same name, different behaviour — mypy sees nothing wrong,
  and auth quietly breaks. So the precise statement is: **a rename/removal is
  caught by the gate; a *semantic* change behind the same name is the silent
  risk** — and that residual case is exactly what Part 3's behavioural wiring test
  closes, because it asserts the *outcome* (a tokenless request gets `401`), not
  the attribute name.

- **The constructor's validation block is skipped.** Setting the attributes by
  hand bypasses step 1.1.2's guard rails. Here we always set both `auth` and the
  verifier together, so the invariant they protect still holds — but we're
  holding it by hand instead of having the SDK enforce it.

### 1.5 Why it was done this way, and the alternatives

This is not sloppiness — it is the **module-level-singleton design (0.1) colliding
with the constructor-injection API (1.1).** You cannot have all of: (a)
module-level `@mcp.tool` decorators, (b) credential-free import, and (c)
constructor-injected auth. Something has to give.

Options:

- **Factory function** — `build_mcp(auth_cfg) -> FastMCP` that constructs the
  server *with* `auth=`/`token_verifier=` and registers the tools inside it,
  called from `main()`. This uses the public API and gets the validation. The
  cost: tools can no longer be decorated at module level on a global `mcp`; they
  move inside the factory (or get registered via a different mechanism). That's a
  real refactor of the whole file.
- **Public setter** — there isn't one. The SDK genuinely does not expose a
  supported way to attach a verifier after construction. That absence is *why*
  the code resorts to the underscore attribute.
- **Keep the private write, but quarantine and document it** (see Part 3). The
  pragmatic middle path.

The takeaway: the private-attribute write is a deliberate, SDK-version-coupled
seam forced by the architecture. The right response isn't necessarily to remove
it — it's to *name it as such* and make it fail loudly instead of silently.

---

## Part 2 — `# pragma: no cover`: what "100% coverage" is not telling you

### 2.0 What coverage and a "pragma" even are — from scratch

Like 0.4.1, we'll build this from the ground up, because the punchline only bites
once three plain ideas are clear: what a test run secretly knows, what a *pragma*
is, and why putting one on `main()` is both reasonable and a trap.

**What a test run secretly knows.** The obvious output of running the tests is
pass/fail. But there's a second thing the tooling can do at the same time: while
the tests run, it **watches your source code and ticks off every line as it
actually executes.** The picture to hold is a **building inspector trailing a tour
group**: every room someone walks into gets a checkmark; rooms nobody enters stay
blank. At the end you get a map of which lines the tests actually *caused to run*.
That map is **code coverage**, and "100% coverage" is just: of all the lines we're
counting, what fraction got a checkmark. (Our `branch = true` config sharpens it —
for an `if`, it tracks not only "did this line run" but "did we go *both* the true
*and* the false way.")

**What that checkmark does *not* mean.** A checkmark means only "this line
executed during some test." It does **not** mean the line is correct, or that any
test *asserted* anything about what it did — a line can get its checkmark purely as
a side effect of a test aimed at something else. So coverage measures
**execution**, not **verification**. That gap is worth filing away, but it's not
today's problem; today's problem is the next idea.

**What a "pragma" is.** New word. A **pragma** (from "pragmatic") is a special
comment that is *not aimed at your program at all* — it's a message to a **tool**
that reads your code. The program ignores it completely; the tool obeys it. The
analogy: a **stage direction in a script.** The actors never say "*exit, pursued
by a bear*" aloud — but the director acts on it. Pragmas exist across many
languages and tools, always meaning roughly *"dear tool, here is a local
instruction about how to treat this particular bit of code."*

`# pragma: no cover` is one such instruction, and the tool it speaks to is the
coverage inspector. It says: *"Inspector — don't tick this line, and don't hold
its blankness against me either. Skip it entirely."* The marked line (or, on a
`def`, the whole function) is removed from **both** sides of the fraction: it is
not counted as "covered," and not counted as "missing." It becomes **uncounted.**

**The trap, stated once and plainly.** A pragma does **not** make code tested. It
makes code *invisible to the measurement.* So "100% coverage" in the presence of a
pragma honestly reads **"100% of the lines we chose to count."** The excluded
region could be flawless or catastrophically broken — the number cannot tell you,
because it isn't looking there. (That single sentence is the whole of 2.2; the
rest of Part 2 is just *which* region we excluded and why it matters.)

**Why it lives on the stdio entrypoint specifically.** Now anchor it in `main()`.
Its `def main()` line carries `# pragma: no cover`, which excludes the entire
function body. *Why does that pragma exist at all?* Because of where `main()` sits
in the building: it is the **front door.** Its job ends in `mcp.run(...)`, the line
that launches the real server and blocks forever. You cannot have the inspector's
tour group "walk through" the front door in a test, because walking through it
means starting a live server — and for HTTP, needing a live IdP — which is exactly
the live-network thing the hermetic rule forbids (0.5.2). So originally the pragma
was *honest*: `main()` was a launcher, and a launcher has nothing in it *to* test
but the launch itself. Excluding an un-walkable front door costs nothing.

The trap (developed in 0.5.1 and 2.3) is what phase 2 did next: it installed real,
testable **wiring** — auth construction, URL coercion, the `_token_verifier`
assignment — *inside* that same front-door function, under the same pragma. So the
inspector now skips not just the un-walkable door, but a roomful of furniture
assembly happening just inside it. The 100% stays serenely green while the most
bug-prone lines in the file go uninspected. Keep that image; the next three
sub-sections make it precise.

### 2.1 What coverage measures, mechanically

Coverage instrumentation watches the test run and records which lines (and, with
`branch = true` as configured here, which branch directions) actually executed.
The gate enforces `--cov-fail-under=90`; this project has historically sat at
100%. "100% coverage" therefore sounds like "every line is tested."

It isn't quite. Coverage measures **execution**, not **correctness** — a line can
run during a test that asserts nothing meaningful about it. And, more to the point
here, coverage only counts lines it is *allowed* to count.

### 2.2 What `# pragma: no cover` does

`# pragma: no cover` is a marker that tells the coverage tool: *do not count this
line — neither as covered nor as missing.* The line vanishes from both the
numerator and the denominator. (This project uses coverage's default exclusion
rules; `pyproject.toml` adds no custom `exclude_lines`, so the literal
`# pragma: no cover` is the mechanism.)

So the honest reading of the number is: **"100% of the lines we did not exclude."**
The pragma doesn't make code tested; it makes code *uncounted*.

CLAUDE.md §4 sanctions exactly one such pragma — `main()` in `server/app.py` —
specifically so the team isn't tempted to sprinkle pragmas everywhere to keep the
number green. That restraint is good. But it means the one excluded region
deserves scrutiny precisely *because* it's the only blind spot.

### 2.3 What is actually inside the blind spot

`main()` is not a trivial one-liner. In the HTTP + auth branch it does, in order:

```python
auth_cfg = load_auth_config()                       # read MCP_AUTH_* env
verifier = IdpTokenVerifier(..., http_client=httpx.AsyncClient())
mcp.settings.auth = AuthSettings(
    issuer_url=AnyHttpUrl(auth_cfg.issuer),
    resource_server_url=AnyHttpUrl(auth_cfg.audience),
    required_scopes=auth_cfg.required_scopes or None,
)
mcp._token_verifier = verifier                      # the Part 1 seam
mcp.settings.host = t.host
mcp.settings.port = t.port
mcp.run(transport="streamable-http")
```

Every one of those lines is excluded from coverage.

Now notice **which** part of the system this is. The verifier's *logic* is tested
in isolation (`test_server_auth.py` exercises `verify_token` against a generated
keypair). The transport *decision* is tested (`test_server_transport.py` covers
`resolve_transport`). The auth-config *parsing* is tested (`load_auth_config`).
The tested units are the easy, pure, in-isolation pieces.

What is **not** tested is the **glue that connects them** — the lines above. That
glue is where the most error-prone questions live, and every one of them is
answered only at real runtime:

- Did we set the right attribute name (`_token_verifier`)? — Part 1's silent
  failure hides exactly here.
- Does `AnyHttpUrl(auth_cfg.audience)` accept the audience string? Audiences are
  often *not* URL-shaped (e.g. an API identifier). If it isn't, `AnyHttpUrl`
  raises — but only when `main()` runs, never in a test.
- Does `required_scopes=... or None` hand the SDK the shape it wants?
- Does `mcp.run(transport="streamable-http")` actually pick up `settings.auth`
  and install the middleware?

This is the general law of integration seams: **the unit pieces are easy to test
and usually right; the wiring between them is hard to test and usually where bugs
live.** And here the wiring is precisely the part hidden under the pragma.

### 2.4 Why excluding it is nonetheless defensible

You genuinely cannot exercise the *full* `main()` in a hermetic unit test: the
tail of it (`mcp.run(...)`) starts a real HTTP server and would need a live IdP +
tunnel to mean anything — both forbidden in the test path. So *some* of `main()`
must stay uncovered.

The compensating control is **REVIEW.md §4**: the human runs `curl …/mcp` with no
token and confirms a `401` with the right `WWW-Authenticate` header, confirms the
metadata document, and completes a real OAuth login in ChatGPT. Those manual
checks are standing in for the automated coverage that cannot exist. That's a
reasonable trade — *as long as everyone understands that's what's happening.*

The point of this section is just to make that explicit: **right now the auth
wiring's correctness rests on a human eyeballing a `curl`, not on the gate.** The
green 100% does not cover it.

---

## Part 3 — how the two connect, and the cheap fix

The two fragilities are the same fragility seen twice:

- Part 1: the verifier is attached via a private attribute that could silently
  stop working on an SDK bump.
- Part 2: the line that does it is never executed by a test, so that silent
  failure would *stay* silent through the whole gate.

Together: the worst-case outcome (server boots with no authentication) is both
**easy to introduce** (an SDK rename) and **invisible to CI** (under the pragma).
That combination is what makes it worth a deliberate note rather than a shrug.

Most of the risk is testable **without** breaking the hermetic rule, because
everything *up to* `mcp.run()` is pure: constructing `AuthSettings`, coercing
`AnyHttpUrl`, and assigning attributes need no network. Extract that into its own
function:

```python
def configure_auth(server: FastMCP, auth_cfg: AuthConfig) -> None:
    """Attach OAuth resource-server verification to an already-built server.

    Isolated from main() so the wiring is unit-testable without starting the
    HTTP server. The _token_verifier assignment is an intentional use of an
    SDK-internal attribute (no public setter exists; see scratchpads/
    auth-wiring-seam.md) and is pinned by the test below.
    """
    server.settings.auth = AuthSettings(
        issuer_url=AnyHttpUrl(auth_cfg.issuer),
        resource_server_url=AnyHttpUrl(auth_cfg.audience),
        required_scopes=auth_cfg.required_scopes or None,
    )
    server._token_verifier = IdpTokenVerifier(
        issuer=auth_cfg.issuer,
        jwks_url=auth_cfg.jwks_url,
        audience=auth_cfg.audience,
        http_client=httpx.AsyncClient(),
    )
```

`main()` then calls `configure_auth(mcp, auth_cfg)` and keeps only `mcp.run(...)`
under the pragma. A hermetic test asserts the wiring landed:

```python
def test_configure_auth_attaches_verifier():
    server = FastMCP("t")
    configure_auth(server, AuthConfig(issuer="https://idp.example/",
                                      jwks_url="https://idp.example/jwks",
                                      audience="https://mcp.example/",
                                      required_scopes=["mcp:read"]))
    assert str(server.settings.auth.issuer_url) == "https://idp.example/"
    assert isinstance(server._token_verifier, IdpTokenVerifier)   # pins the name
```

What this buys, against the two fragilities:

- **Pins the private-attribute name (fixes Part 1's silent failure).** If a future
  `mcp` renames or drops `_token_verifier`, `isinstance(...)` fails loudly in CI
  instead of the server quietly booting unauthenticated.
- **Exercises the `AnyHttpUrl` coercion and `AuthSettings` shape (fixes Part 2's
  blind spot).** A malformed audience or wrong scope shape now fails a test, not
  production.
- **Shrinks the `# pragma: no cover` region to just `mcp.run(...)`** — the one
  line that genuinely cannot be unit-tested. The pragma stays honest; almost
  nothing hides behind it.

This is roughly a ten-line move and it resolves both points at once. It is left
as a recommendation, not done, pending the review.

---

## Part 4 — Field log: the seam fired twice in live testing (2026-06-16)

> **Where things stand right now:** the build is **one config change away** from a
> working ChatGPT connection. The server now accepts real Auth0 tokens — auth is
> fully working end-to-end (verified with a real client-credentials token: JWKS
> fetched `200`, signature/`iss`/`aud`/`exp` all validated, request got past the
> auth layer). The **only** remaining blocker is **Bug 2** below: a
> `421 Invalid Host header`. Everything up to that is green.

Bringing the container up behind ngrok + Auth0 (REVIEW §3–§4) produced **two**
real, separately-debugged failures — both exactly what Part 2 predicted:
invisible to the gate, surfaced only by manual `curl`. Recording them as evidence
and as the to-do.

### Bug 1 — audience trailing-slash mismatch (RESOLVED)

- **Symptom:** a valid Auth0 token was rejected with `401`.
- **Cause:** the server advertises its resource as `https://…ngrok-free.dev/` —
  pydantic `AnyHttpUrl` *always* appends a trailing slash in the RFC 9728
  metadata. But the verifier checks the token's `aud` against the **raw**
  `MCP_AUTH_AUDIENCE` string, which had been set (and the Auth0 API identifier
  created) **without** the slash → mismatch → `401`.
- **Time-waster:** the `/.well-known/oauth-protected-resource` metadata showed
  `…dev/` *with* the slash, which *looked* consistent — but that was `AnyHttpUrl`
  normalising the metadata, masking that the raw value the verifier uses had no
  slash. **Lesson: normalised surfaces lie about the raw value; the source of
  truth is `docker compose exec -T server printenv MCP_AUTH_AUDIENCE`.**
- **Also bit us:** the container was running **stale env** — `.env` had been
  corrected but the container wasn't restarted, so it still held the old value.
  **`.env` changes only take effect on `docker compose up`.**
- **Fix applied:** Auth0 API identifier recreated *with* the trailing slash;
  `MCP_AUTH_AUDIENCE=https://your-app.ngrok-free.dev/`; restarted.

### Bug 2 — `421 Invalid Host header` (OPEN — the morning task)

- **Symptom:** with auth now passing, an authenticated request returns
  `421 Misdirected Request`, body `Invalid Host header`. Server log:
  `Invalid Host header: your-app.ngrok-free.dev`.
- **Cause — and it is *this exact seam* (Part 1):** the module-level
  `mcp = FastMCP("tattoo-feed", …)` is constructed **at import** with the SDK's
  default `host="127.0.0.1"`. The constructor auto-enables **DNS-rebinding
  protection** for localhost, freezing the allowed-`Host` list to localhost
  variants. `main()` later sets `mcp.settings.host = "0.0.0.0"` for the real bind
  — **but the transport-security posture was already locked at construction.** So
  every request arriving with the real ngrok `Host` is refused.
- This is the **identical import-time-vs-`main()`-mutation pattern** as the
  `_token_verifier` write — just on `transport_security` instead of `auth`. A
  setting that must reflect the *runtime* (the public host) is instead fixed by
  the *import-time default*, and the post-hoc `settings.host` mutation can't undo
  it.
- And it's the **identical blind spot** as Part 2: it lives in the uncovered
  `main()` HTTP path and was caught only by a manual `curl` in REVIEW §4, never by
  the gate.

### The fix to apply (Bug 2)

In `main()`'s HTTP branch, set transport security explicitly so the public host
is allowed. Two options:

```python
from mcp.server.transport_security import TransportSecuritySettings   # ⚠ confirm import path

# Option A — allow-list the real public host (keeps the defence):
mcp.settings.transport_security = TransportSecuritySettings(
    allowed_hosts=[public_host],                 # e.g. "your-app.ngrok-free.dev"
    allowed_origins=[f"https://{public_host}"],
)

# Option B — disable DNS-rebinding protection for the tunnelled deployment (simpler):
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)
```

- **Recommended:** Option A — derive `public_host` from `MCP_AUTH_AUDIENCE`
  (strip the `https://` and trailing slash) or add an `MCP_PUBLIC_HOST` env var.
  Option B is acceptable here (the real protections are OAuth + ngrok TLS) but
  drops a layer.
- ⚠️ **Confirm the API before applying** — the field names
  (`allowed_hosts`, `allowed_origins`, `enable_dns_rebinding_protection`) and the
  import path were *not* verified this session (the inspection was interrupted).
  One command settles it:
  `uv run python -c "import mcp.server.transport_security as t; print(t.TransportSecuritySettings.model_fields)"`
- **Then:** `docker compose down && docker compose up`, and re-run the token smoke
  test. `421` should become `200`/`400` (past auth *and* past the host check).
  After that, the only thing left is adding the connector in ChatGPT itself.

### How this folds into Part 3

The Part 3 `configure_auth()` extraction should be **widened** — really a
`configure_http(server, cfg)` covering all three import-time-vs-runtime settings:
`auth`, `_token_verifier`, **and `transport_security`**. A hermetic test then
asserts the built server's `settings.transport_security.allowed_hosts` contains
the configured public host — which **would have caught Bug 2 before ngrok was
ever involved.** Two live bugs, in two settings, in this one untested spot — that
is the argument for the extraction, now made concretely rather than
hypothetically.

---

## One-paragraph summary

`app.py` attaches the OAuth token verifier by writing `mcp._token_verifier`, a
private SDK attribute, because the module-level-singleton design means the real
`auth=`/`token_verifier=` constructor parameters aren't available at import time.
It works today only because the SDK reads that attribute lazily at `mcp.run()`,
but a future SDK rename would disable authentication **silently** — and `mypy`
can't see it. That same wiring lives inside `main()`, the one `# pragma: no cover`
region, so **no test ever runs it**; its correctness currently rests entirely on
the manual `curl → 401` check in REVIEW.md §4. Extracting a `configure_auth()`
helper and unit-testing it would pin the attribute name, exercise the URL/scope
coercion, and shrink the uncovered region to just `mcp.run()` — closing both gaps
in about ten lines.
