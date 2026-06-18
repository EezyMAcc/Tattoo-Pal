# The `421 Invalid Host header` — DNS-rebinding protection vs. a tunnelled host

> **Status:** diagnosis complete and empirically verified against the installed
> `mcp` SDK (2026-06-18). This document explains the bug from first principles,
> the fix, and the test changes. It is the resolution writeup for **Bug 2** in
> `auth-wiring-seam.md §4` ("`421 Invalid Host header` — OPEN — the morning
> task"). Bug 1 (the audience trailing-slash `401`) is already resolved there.
>
> This is post-loop remediation, *outside* the phase-3 chunk plan: it touches
> `build_server` and `test_server_auth.py` to fix a live blocker the gate never
> caught. The phase-3 invariants are preserved — auth stays **constructor-
> injected** (see §6), `core` stays MCP-free, the MCP surface is unchanged.

---

## 0. The symptom, exactly

Live, behind ngrok, with auth fully working (Bug 1 fixed, a real Auth0 token in
hand), the **authenticated** MCP request returns:

```
HTTP/2 421 Misdirected Request
body: Invalid Host header
server log: Invalid Host header: your-app.ngrok-free.dev
```

In the ngrok inspector the pattern was:

| Request | Status | Why |
|---|---|---|
| `POST /mcp` (no token) | `401` | auth middleware rejects — *expected* handshake |
| `GET /.well-known/oauth-protected-resource` | `200` | metadata is public, not host-checked |
| `POST /mcp` (**valid token**) | **`421`** | **passes auth, then fails the Host check** |

The token was never the problem. The request dies *after* authentication, at a
transport-layer Host-header check it never reached in any automated test.

---

## 1. First principles — what is "DNS-rebinding protection" and why does an MCP server have it?

### 1.1 The attack it defends against

**DNS rebinding** is a browser attack that turns a victim's browser into a proxy
onto services bound to `localhost` (or a private LAN) that the attacker cannot
reach directly.

The mechanics, from scratch:

1. The victim visits `evil.example`. The attacker controls its DNS, and answers
   with a **short TTL** so the browser will re-resolve the name almost
   immediately.
2. The page's JavaScript makes `fetch()` calls back to `evil.example`.
3. Between the first and second request the attacker **rebinds** the DNS name:
   `evil.example` now resolves to `127.0.0.1`.
4. The browser, believing it is still talking to the *same origin*
   (`evil.example`), happily sends requests — but they now land on a service
   listening on the victim's own `localhost`: a local dev server, a desktop
   agent, a database admin UI, an **MCP server**.
5. The Same-Origin Policy doesn't save you: from the browser's point of view the
   origin never changed; only the IP underneath it did.

So a web page anywhere on the internet can drive a local-only service that
assumed "if you can reach me on `localhost`, you must be trusted."

### 1.2 The defence: validate the `Host` header

The server cannot trust the *socket* (the attacker rebinds the IP), but it
**can** check the `Host` header the browser sends. The browser, talking to
"`evil.example`", sends `Host: evil.example`. A localhost-only service that
only ever expects `Host: localhost` or `Host: 127.0.0.1` can **reject** any
request whose `Host` is something else — `421 Misdirected Request`, "you sent
this to the wrong place."

That is exactly what the MCP SDK does. From the installed SDK
(`mcp/server/transport_security.py`), `_validate_host`:

```python
def _validate_host(self, host: str | None) -> bool:
    if not host:
        return False                       # no Host -> reject
    if host in self.settings.allowed_hosts:  # exact match
        return True
    for allowed in self.settings.allowed_hosts:  # "<base>:*" wildcard-port match
        if allowed.endswith(":*") and ... :
            return True
    return False
```

`421 Misdirected Request` is the HTTP status meaning "this request was directed
at a server that is not configured to respond to it" — the precise semantics for
a Host the server doesn't claim.

### 1.3 Why this fires for *us*, when we are not under attack

The protection keys off a list, `allowed_hosts`. Our server is legitimately
reached as `your-app.ngrok-free.dev` — a host that was **never put
on the list**. The defence cannot tell "ngrok forwarding a real user" from
"`evil.example` rebound to localhost"; both arrive with a `Host` the server
didn't pre-declare. So a correct, authenticated request is refused. The defence
is doing its job; we simply never told it our public name.

### 1.4 Is DNS rebinding actually a risk for *this* deployment? (Mostly no — read this before "fixing" it)

It is worth being blunt: **for this server, as deployed, DNS rebinding is not a
meaningful threat.** The `421` is the SDK applying a default tuned for a
*different deployment shape* than ours. Understanding this is the difference
between "make the error go away" and "know what the control is for."

The attack requires **all three** of the following to hold. Each is a link in the
chain; break any one and the attack is impossible:

1. **A browser is the confused deputy.** Rebinding works by getting a *victim's
   browser* to run attacker JavaScript that then issues requests to the target.
   The browser is the thing being tricked. No hostile-JS-running browser pointed
   at the target → no attack.
2. **The target is otherwise unreachable, and trusts by network position.** The
   entire payoff is reaching something the attacker *cannot reach directly* — a
   service bound to `localhost` or a private LAN — by borrowing the victim's
   network position. The target must treat "you connected to my socket" as "you
   are trusted."
3. **There is no credential gate.** If the target demands a secret that the
   injected JS does not possess, rebinding onto it accomplishes nothing.

Now hold our deployment against each link:

| Requirement for the attack | This server | Link holds? |
|---|---|---|
| Browser deputy running attacker JS at the target | Clients are **server-to-server** — ChatGPT's *backend* calls `/mcp`. No victim browser issues requests to it. | ✗ broken |
| Unreachable target, trusted by network position | The server is on a **public ngrok HTTPS URL** — anyone can reach it directly. There is no localhost/LAN position to steal. | ✗ broken |
| No credential gate | Every `/mcp` call needs a **valid Auth0 bearer token** (signature + `iss` + `aud` + `exp`). A rebound browser has no token → `401`. | ✗ broken |

All three links are broken, independently. Rebinding's whole point is to reach
something you *can't* reach directly; a public URL is reachable by definition,
and it is token-gated on top. The threat model simply does not fit.

**So why does the SDK turn the protection on by default?** Because the SDK's
default is `host="127.0.0.1"` — a *localhost-bound dev server, usually with no
auth*. That is the **canonical DNS-rebinding target**: an MCP server on a
developer's laptop that a malicious web page could rebind onto and drive. For
that default shape the protection is exactly right and should stay on. The SDK
cannot know we are public, tunnelled, and OAuth-gated, so it ships the cautious
default — and we walk into it.

**Then why fix it with an allow-list (Option A) rather than just deleting the
control?** Precisely *because* the control is not load-bearing here, the choice is
about **hygiene, not security** — see §4. We keep it on and name our real host so
the configuration documents its own intent and stays correct if the deployment
later grows a browser-facing surface. We are not relying on it to stop a live
attack; OAuth + TLS already do that.

---

## 2. The mechanism — where the allow-list comes from, and why it's wrong for us

This is the crux, and it is the **same seam** as the phase-3 `_token_verifier`
write (Part 1 of `auth-wiring-seam.md`): a setting that must reflect the
**runtime** is instead frozen from an **import-time default**, and a later
mutation cannot undo it.

### 2.1 `allowed_hosts` is derived from `host` at construction time

Empirically, against the installed SDK:

```
>>> TransportSecuritySettings()                       # the bare default
enable_dns_rebinding_protection = True
allowed_hosts  = []
allowed_origins = []

>>> FastMCP("t").settings.transport_security          # what construction bakes
enable_dns_rebinding_protection = True
allowed_hosts   = ['127.0.0.1:*', 'localhost:*', '[::1]:*']
allowed_origins = ['http://127.0.0.1:*', 'http://localhost:*', 'http://[::1]:*']
```

Two facts that matter:

1. DNS-rebinding protection is **on by default** (`True`).
2. `FastMCP.__init__` takes its `host` parameter (default `"127.0.0.1"`) and
   **auto-populates** `allowed_hosts` with the localhost family. The allow-list
   is computed **once, at construction**, from the host the constructor was
   given.

### 2.2 `settings.host = "0.0.0.0"` afterwards does nothing for security

Our `main()` did:

```python
server = build_server(load_auth_config())   # constructed with default host -> localhost-locked
server.settings.host = t.host               # "0.0.0.0"  — too late
server.settings.port = t.port
server.run(transport="streamable-http")
```

`server.settings.host = "0.0.0.0"` changes the **bind address** (what socket
uvicorn listens on) but does **not** re-run the construction-time derivation of
`transport_security`. The allow-list is still the localhost family. And even if
it did re-derive, `"0.0.0.0"` is a bind address, not the *public name* the
`Host` header carries — so it still wouldn't contain `your-app...ngrok-free.dev`.

This is "a setting that must reflect the runtime is fixed by the import-time
default, and the post-hoc mutation can't undo it" — verbatim the
`_token_verifier` pattern, on `transport_security` instead of `auth`.

### 2.3 Why the fix is nonetheless simple: the middleware reads `transport_security` *live*

Crucially — and unlike `host` — the middleware reads
`self.settings.transport_security` **at request time**, not at construction. So
**assigning a fresh `TransportSecuritySettings` after construction works.**
Verified:

```
FastMCP, localhost-locked, Host=<ngrok>            GET /mcp -> 421   # blocked
FastMCP, transport_security reassigned to allow it GET /mcp -> 406   # past the host check
```

`406 Not Acceptable` here just means "host OK, but a bare `GET` isn't a valid
MCP call" — the point is it is **past** the `421`. So the fix is not to fight the
construction-time bake; it is to **reassign `transport_security` to a value that
names our real host.** The only question is *where* to do it so it is tested.

---

## 3. The finding that should not be skipped — a test was green while broken

The phase-3 gate was green. Yet the live `421` existed the whole time. How did no
test catch a valid token failing? Because the one test that exercises a valid
token over HTTP asserted too loosely.

`test_valid_token_is_accepted` (current):

```python
response = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})
# Auth passed: the MCP endpoint itself may return any non-auth error
assert response.status_code not in (401, 403)
```

The `TestClient` default base URL is `http://testserver`, so the request carries
`Host: testserver` — which is **not** in the localhost-locked allow-list. Running
that exact path and printing the status:

```
>>> VALID TOKEN, Host=testserver: status = 421
>>> body: Invalid Host header
```

`421 not in (401, 403)` is `True`, so the assertion **passes**. The test has been
green while the valid-token request never once reached the MCP layer — it died at
the host check, invisibly. This is the same family as Part 2 of
`auth-wiring-seam.md` (coverage that "isn't telling you" something): a *green
assertion* that wasn't telling us the request actually succeeded.

It also confirms the **middleware order**: auth runs **before** the host check.
That is why tokenless probes are `401` (short-circuited at auth, never reaching
the host check) while the valid-token call is `421` (passes auth, then host
check). The order is what makes the live 401/421 split sensible.

---

## 4. The fix (code)

Do the transport-security configuration **inside `build_server`**, gated on
`auth_cfg` being present, deriving the public host from `auth_cfg.audience` — the
*same single source of truth* the token `aud` check already uses
(`MCP_AUTH_AUDIENCE`). This moves the logic **out of the uncovered `main()` and
into the gated `build_server`**, which is what makes it testable.

`src/tattoo_feed/server/app.py`:

```python
from urllib.parse import urlparse
from mcp.server.transport_security import TransportSecuritySettings


def _public_host(audience: str) -> str:
    """Extract the bare host[:port] from the resource-server audience URL.

    The audience (``MCP_AUTH_AUDIENCE``) is the canonical public URL of this
    server, e.g. ``https://your-app.ngrok-free.dev/``. The Host
    header arriving through the tunnel carries exactly this netloc, so it is the
    correct value to add to the DNS-rebinding allow-list.
    """
    return urlparse(audience).netloc


def build_server(auth_cfg: AuthConfig | None) -> FastMCP:
    if auth_cfg is not None:
        server = FastMCP(
            "tattoo-feed",
            instructions=_INSTRUCTIONS,
            auth=AuthSettings(...),               # UNCHANGED — constructor-injected
            token_verifier=IdpTokenVerifier(...), # UNCHANGED — constructor-injected
        )
        # The one import-time-vs-runtime setting that the constructor cannot get
        # right for a tunnelled deployment: re-point DNS-rebinding protection at
        # the real public host. Reassigning transport_security after construction
        # IS honoured by the middleware (it reads the value per-request), unlike
        # the settings.host mutation, which is not.
        host = _public_host(auth_cfg.audience)
        server.settings.transport_security = TransportSecuritySettings(
            allowed_hosts=[host, f"{host}:*", "127.0.0.1:*", "localhost:*"],
            allowed_origins=[f"https://{host}"],
        )
    else:
        server = FastMCP("tattoo-feed", instructions=_INSTRUCTIONS)
    ...
```

Design notes:

- **Auth stays in the constructor.** Phase 3's achievement was moving auth onto
  public constructor parameters; we do **not** fold it back into a
  post-construction `configure_http` mutation. Only `transport_security` —
  genuinely unfixable at construction for a tunnelled host — is set afterward.
- **Localhost is retained** in `allowed_hosts` so in-container access and any
  `localhost` health check still work; we *add* the public host rather than
  replacing the family.
- **Derive from the audience, add no new env var.** One value
  (`MCP_AUTH_AUDIENCE`) now drives both the token `aud` binding and the Host
  allow-list — they cannot drift apart.
- **No-auth (stdio) path is untouched**: it keeps the localhost-locked default,
  which is correct (stdio serves no HTTP). Running unauthenticated HTTP over a
  public tunnel is not a supported configuration; with no `auth_cfg` there is no
  audience to derive a host from.
- **`main()` simplifies**: it still binds `0.0.0.0`, but no longer carries any
  (ineffective) security responsibility — the security posture is now decided in
  the tested factory.

### Why Option A, when the control isn't load-bearing (§1.4)

Be clear about what we are *not* claiming: per §1.4, DNS rebinding is not a real
threat against this server, so **neither option meaningfully changes our security
posture.** OAuth + TLS are the controls that actually matter, and they are
untouched either way. This is a choice between two equally-safe options, decided
on hygiene — not a security trade-off.

**Option B — disable the protection.**

```python
TransportSecuritySettings(enable_dns_rebinding_protection=False)
```

Honest and minimal: it stops asserting a localhost-shaped defence on a public,
token-gated server. Perfectly defensible. Its only downside is that it throws the
control away entirely, so if the deployment later sprouts a browser-facing
surface (a widget origin served directly, a different bind, a non-tunnelled
host), the protection is silently gone and nobody re-derives it.

**Option A — allow-list the real host (chosen).**

```python
TransportSecuritySettings(
    allowed_hosts=[host, f"{host}:*", "127.0.0.1:*", "localhost:*"],
    allowed_origins=[f"https://{host}"],
)
```

Chosen for three **hygiene** reasons, none of them "it blocks an attack we are
exposed to":

1. **It documents intent.** The config now states, in code, the exact public
   identity the server answers to. A reader sees *what* host this server is,
   not just that a check was switched off.
2. **It fails safe under future change.** If someone later adds a browser-facing
   surface or changes the bind, the control is still on and still scoped to a
   named host — it degrades to "reject the unexpected" rather than "allow
   everything."
3. **It costs nothing.** We already have the canonical host for free (it is the
   audience), so keeping the defence on is zero extra configuration and one
   derived value.

In short: we keep Option A as cheap defence-in-depth and self-documenting config,
**not** because we believe rebinding can reach this server. If a future reader
prefers to be maximally honest that the threat doesn't apply, Option B with a
one-line comment ("public, token-gated server — not a localhost rebinding
target") is an equally legitimate choice.

---

## 5. The fix (tests) — `tests/test_server_auth.py`

The test changes do two jobs: **catch this class of bug in the gate**, and
**un-mask** the existing too-loose assertion.

### 5.1 New — the test that would have caught Bug 2 before ngrok

```python
def test_build_server_allowlists_audience_host() -> None:
    """build_server adds the audience's host to the DNS-rebinding allow-list."""
    server = build_server(_test_auth_cfg())          # audience = https://mcp.example.com/
    hosts = server.settings.transport_security.allowed_hosts
    assert "mcp.example.com" in hosts
```

A pure, fast assertion on the *built server's settings* — no HTTP, no tunnel.
This is the direct realization of the scratchpad's claim that such a test "would
have caught Bug 2 before ngrok was ever involved."

### 5.2 New — lock the stdio (no-auth) posture

```python
def test_build_server_no_auth_keeps_localhost_lock() -> None:
    """Without auth, the server keeps the localhost-locked default (stdio posture)."""
    server = build_server(None)
    hosts = server.settings.transport_security.allowed_hosts
    assert "127.0.0.1:*" in hosts
    assert all("ngrok" not in h and "mcp.example.com" not in h for h in hosts)
```

Pins the deliberate asymmetry: only the authenticated HTTP build opens the host
list; the local/stdio build stays locked down.

### 5.3 Fix — tighten the masked valid-token test

The request must now be driven with the **allow-listed** host, and the assertion
must **exclude `421`** so a host-check failure can no longer hide:

```python
def test_valid_token_is_accepted(rsa_private_key, jwks_body) -> None:
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    starlette_app = build_server(_test_auth_cfg()).streamable_http_app()
    token = _make_token(rsa_private_key)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # Drive the request as the allow-listed audience host (mcp.example.com),
        # not the TestClient default "testserver" — otherwise the DNS-rebinding
        # host check (correctly) returns 421 before the MCP layer is reached.
        with TestClient(
            starlette_app,
            base_url="https://mcp.example.com",
            raise_server_exceptions=False,
        ) as client:
            response = client.get(
                "/mcp", headers={"Authorization": f"Bearer {token}"}
            )
    # Past auth AND past the host check: 421 is now explicitly disallowed.
    assert response.status_code not in (401, 403, 421)
```

**Anti-cheat compliance (CLAUDE.md golden rule 1).** This is a permitted test
update: the replacement assertion `not in (401, 403, 421)` is **strictly
stronger** than the original `not in (401, 403)` — it *removes* a hole rather
than widening one, and it makes the test finally prove what its name claims (a
valid token is *accepted*, i.e. reaches the handler). Driving the client with the
real host is required *because* of the fix, not to dodge a failure.

### 5.4 New — prove the defence is still live (not just switched off)

```python
def test_disallowed_host_still_rejected(rsa_private_key, jwks_body) -> None:
    """A valid token from a non-allow-listed Host is still refused with 421."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    starlette_app = build_server(_test_auth_cfg()).streamable_http_app()
    token = _make_token(rsa_private_key)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with TestClient(
            starlette_app, base_url="https://evil.example", raise_server_exceptions=False
        ) as client:
            response = client.get(
                "/mcp", headers={"Authorization": f"Bearer {token}"}
            )
    assert response.status_code == 421
```

This is the counterpart to 5.3: 5.3 proves the *right* host gets through, 5.4
proves a *wrong* host is still blocked — together they show the allow-list is
narrowed to exactly our host, not disabled.

### 5.5 The other existing auth tests are unaffected — and why

| Test | Host used | Path | Still correct? |
|---|---|---|---|
| `test_unauthenticated_request_gets_401` | testserver | tokenless → auth `401` *before* host check | ✓ unchanged |
| `test_wrong_scope_gets_403` | testserver | bad scope → auth `403` *before* host check | ✓ unchanged |
| `test_wrong_audience_token_gets_401` | testserver | bad `aud` → auth `401` *before* host check | ✓ unchanged |
| `test_protected_resource_metadata_is_served` | testserver | `/.well-known/...` not host-checked | ✓ unchanged |

All four short-circuit *before* the host check (auth first; metadata is public),
so leaving them on `Host: testserver` is fine. Only the valid-token path reaches
the host check, which is why only 5.3 needed the allow-listed host.

---

## 6. Why this is the correct altitude, and what it does *not* change

- **Phase-3 invariants preserved.** Auth/token_verifier remain
  constructor-injected; no `_token_verifier`-style private write returns; `core`
  stays MCP-free; the 11-tool + widget surface is untouched. `grep -n
  "_token_verifier" src` stays clean.
- **Coverage improves, honestly.** The security decision moves from the
  `# pragma: no cover` `main()` tail into `build_server`, which the gate
  exercises. The new §5.1/§5.2 assertions cover both branches (auth host added /
  no-auth locked). The pragma region shrinks further toward just the `run()`
  tail.
- **One source of truth.** `MCP_AUTH_AUDIENCE` now governs token `aud` *and* the
  Host allow-list. Bug 1 (audience mismatch) and Bug 2 (host mismatch) can no
  longer disagree — they read the same value.

---

## 7. Deploy + verify (human steps, post-merge)

1. Apply §4/§5; run the full gate (all four commands green; coverage ≥ 90%).
2. `docker compose down && docker compose up --build` — code **and** `.env`
   changes only take effect on a fresh up (the stale-env lesson from Bug 1).
3. Re-run the smoke: authenticated `POST /mcp` should now be `200`, **not** `421`.
4. In ChatGPT, the connector should discover all 11 tools; then the §6 eyeball
   check in `REVIEW.md` (widget image render) is the only remaining human gate.

---

## 8. One-paragraph summary

The MCP SDK turns on DNS-rebinding protection by default and freezes its
`allowed_hosts` list from the `FastMCP` constructor's `host` parameter
(localhost). Behind ngrok, requests arrive with `Host:
<name>.ngrok-free.dev` — not on the list — so every authenticated call is
refused with `421` *after* passing auth. The late `settings.host = "0.0.0.0"`
mutation in `main()` cannot fix it (same import-time-vs-runtime seam as the
phase-3 `_token_verifier` write), but **reassigning `transport_security` after
construction is honoured by the middleware**. Note the honest framing (§1.4):
DNS rebinding is *not* a real threat against this server — it is public,
server-to-server, and OAuth-gated, none of which the rebinding attack can defeat;
the protection is an SDK default aimed at localhost dev servers. So the fix is
**hygiene, not security**: we keep the control on and allow-list our real host
(derived from `MCP_AUTH_AUDIENCE`) so the config self-documents and fails safe
under future change, rather than disabling it. It is set inside the tested
`build_server`, keeping auth constructor-injected. A new settings-assertion test
catches this in the gate, and the previously-masked `test_valid_token_is_accepted`
(green while silently returning `421`) is tightened to exclude `421` and driven
from the allow-listed host — strictly stronger than before, and finally proving
what it claims.
