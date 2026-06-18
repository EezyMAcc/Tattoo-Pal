# Tattoo Feed

> A calm, bounded way to spend time with the tattoo artists you admire — inside
> your AI chat, without Instagram's feed.

Tattoo Feed brings an artist's recent work to you **one piece at a time**, in a
conversation, so you can sit with it, react, keep what resonates, and over time
see how your own taste shows up across real work. It is the opposite of an
infinite algorithmic scroll: you look at what you asked for and leave when
*you're* done, not when a feed decides to release you.

Under the hood it is a **Model Context Protocol (MCP) server**. You point it at
the artists you follow (by Instagram handle); from your chat client you can pull
a merged feed, discover one post at a time, bookmark favourites, and record notes
about your taste that a future session can reload. Recent work is fetched through
Instagram's **Business Discovery** API.

**The image renders inline only in ChatGPT.** `next_inspiration` returns a
ChatGPT **Apps SDK widget** that draws the preview image directly in the
conversation. This matters because no other tested client shows the image inline
— ChatGPT does not render raw MCP image blocks, and Claude *receives* the image
but does not display it. Since *actually seeing the work* is the whole point, the
product targets the ChatGPT connector over HTTP. A stdio transport exists for
local development, but it does not render the image.

> Read-and-curate only: Tattoo Feed never posts, comments, or messages, and
> previews are downscaled copies — see [Attribution](#attribution--copyright).

---

## How it works

```
You ──▶ ChatGPT ──(OAuth-gated HTTP)──▶ Tattoo Feed (MCP server) ──▶ Instagram
                                            │                         Business
                          renders the  ◀────┘  next_inspiration         Discovery
                          Apps SDK widget       returns a widget +
                          (image inline)        downscaled preview
```

- **MCP tools** expose the actions (track artists, pull a feed, discover one
  piece, save, record taste). See [The MCP tools](#the-mcp-tools).
- **Two-layer codebase**: all logic lives in a transport-agnostic `core`; a thin
  `server` adapter exposes it as MCP. See [Repository layout](#repository-layout).
- **OAuth 2.1 resource server**: in HTTP mode every request must carry a valid
  bearer token from your identity provider. An unauthenticated request gets `401`
  with a `WWW-Authenticate: Bearer resource_metadata=...` header (RFC 9728); the
  ChatGPT connector follows this to complete login automatically.
- **The widget**: the ≤640px preview travels as a data URL in the tool result's
  `_meta`, which the ChatGPT host forwards to the widget iframe without ever
  putting the base64 through the model's context window.

---

## Repository layout

### Code — `src/tattoo_feed/`

A deliberate two-layer split so a future GUI can reuse the logic without a
rewrite. **`core` knows nothing about MCP; `server` holds no business logic.**

```
src/tattoo_feed/
  config.py            # lazy env config (IG_ACCESS_TOKEN, IG_USER_ID)
  errors.py            # typed error hierarchy (TattooFeedError + subclasses)
  models.py            # Pydantic v2 frozen value objects
  imaging.py           # preview downscale + EXIF strip (≤640px JPEG)
  repositories/        # Repository ABC + JSON-file stores (atomic writes)
  graph/client.py      # Instagram Business Discovery client
  services/            # Feed / Artist / Inspiration / Preference services
  server/app.py        # build_server() factory; MCP tools; stdio/HTTP entrypoint
  server/auth.py       # OAuth 2.1 JWT verifier (resource-server side)
  server/widgets/      # Apps SDK widget HTML, served as a ui:// MCP resource
```

`tests/` mirrors this with a fully **hermetic** suite — Instagram HTTP is mocked
with `respx`, JWKS with test-generated RSA keypairs, zero live network calls.

### Non-code documentation

The repo keeps two kinds of written record alongside the code. Neither is needed
to run the project; both are kept deliberately, as a window into how it was built.

- **`scratchpads/`** — *in-build engineering notes and design deep-dives.* The
  working reasoning behind specific decisions and bug investigations, written as
  they happened: e.g. `removing-the-global.md` (why the module-level server
  global was removed), `auth-wiring-seam.md` and `host-header-421.md` (an auth
  refactor and the DNS-rebinding `421` it surfaced), `rate-limiting.md`,
  `built-for-chatgpt.md`. Think of these as the project's lab notebook.

- **`build_artifacts/`** — *an archived record of the phased build.* The project
  was built in stages (`Phase 1`–`Phase 3`), each driven by its own governing
  docs — an implementation plan, a technical-contract reference, process rules,
  and an acceptance checklist — plus the autonomous build-loop scripts and the
  per-phase build logs. It is purely historical: a snapshot of *how* each stage
  was specified and run, not live configuration.

- **Root docs** — `RETROACTIVE_PRD.md` reconstructs, at product altitude, the
  *why / for whom / what "good" means* (a teaching artifact written after the
  fact); `CLAUDE.md` is the process governance for the build tooling.

---

## Setup

Requirements: **Python 3.12** and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # create the venv and install pinned deps
cp .env.example .env    # then edit .env with your real credentials
```

### Environment variables

**Always required — Instagram credentials:**

| Variable | Meaning |
|---|---|
| `IG_ACCESS_TOKEN` | A long-lived Instagram Graph API access token. |
| `IG_USER_ID` | The Instagram **Business/Creator account id** that owns the token (not your Facebook user id). |
| `TATTOO_FEED_DATA_DIR` | Optional. Where the JSON stores live (default `./data`). |

**Required for HTTP / ChatGPT mode — OAuth resource-server config:**

| Variable | Meaning |
|---|---|
| `MCP_AUTH_ISSUER` | Issuer URL of your IdP — must exactly match the token's `iss` claim. |
| `MCP_AUTH_JWKS_URL` | JWKS endpoint used to verify JWT signatures. |
| `MCP_AUTH_AUDIENCE` | Canonical public URL of this server — the RFC 8707 audience binding. |
| `MCP_AUTH_REQUIRED_SCOPES` | Comma-separated required scopes (blank for none). |
| `NGROK_AUTHTOKEN` / `NGROK_DOMAIN` | ngrok auth token and your reserved domain for stable TLS ingress. |

`.env` is gitignored and must never be committed — only `.env.example` (with
placeholders) is in the repo.

> **Getting Instagram credentials** is a one-time manual step on Meta's side:
> create a Meta app, link an Instagram **Business/Creator** account to a Facebook
> **Page**, and mint a long-lived token with Business Discovery permission. The
> `IG_USER_ID` must be the *Instagram account id* (via
> `GET /me/accounts?fields=instagram_business_account`), not your Facebook user id.

---

## Running

### ChatGPT over HTTP — the product

`./run-server.sh` builds the image and starts the server + ngrok tunnel together
(a thin wrapper over `docker compose up --build`):

```bash
cp .env.example .env            # fill in all values, including MCP_AUTH_* and NGROK_*
./run-server.sh
```

Then:

1. Open the ngrok inspector at `http://localhost:4040` to confirm the public URL.
2. In ChatGPT, add a **custom connector**:
   - URL: `https://<your-ngrok-domain>/mcp`
   - Authentication: **OAuth**
3. ChatGPT walks through OAuth discovery and a browser login against your IdP,
   then lists the tools.

**Identity provider.** The server is IdP-agnostic — it only needs an issuer
supporting OAuth 2.1 + PKCE, metadata discovery (RFC 8414 / OIDC), and the RFC
8707 `resource` indicator. [Auth0](https://auth0.com/blog/add-remote-mcp-server-chatgpt/)
has a documented walkthrough for exactly this setup (Stytch, WorkOS, Descope are
alternatives). Configure your IdP to issue tokens whose audience is the server's
public URL (`MCP_AUTH_AUDIENCE`), and register a matching API/resource for it.

**Stable domain.** Reserve a domain at
<https://dashboard.ngrok.com/domains> and set `NGROK_DOMAIN` in `.env`, so the
public URL — and the connector configuration — survive restarts.

### Local development (stdio)

A credential-free local entrypoint, useful for exercising the tools without a
tunnel or IdP, and the transport the test suite boots over. **It does not render
the inspiration image** — use ChatGPT for the visual experience.

```bash
uv run python -m tattoo_feed.server.app
```

Wire it into a local MCP client with `command: "uv"`,
`args: ["run", "python", "-m", "tattoo_feed.server.app"]`, the project as `cwd`,
and `IG_ACCESS_TOKEN` / `IG_USER_ID` in `env`.

---

## The MCP tools

| Tool | What it does |
|------|--------------|
| `list_artists` | List tracked artists. |
| `add_artist(handle)` | Validate the handle is a reachable **professional** account, then track it. |
| `remove_artist(handle)` | Stop tracking a handle. |
| `get_feed(limit_per_artist=10)` | Merged, newest-first feed — metadata + permalinks only (no images). |
| `next_inspiration()` | One **not-yet-seen** post, marked seen. Returns the Apps SDK widget; image renders inline **only in ChatGPT**. |
| `save_to_inspiration(post_id, notes=None)` | Bookmark a post into the saved collection. |
| `list_inspiration()` | The saved collection, in save order. |
| `remove_from_inspiration(post_id)` | Remove a saved item. |
| `reset_seen()` | Clear the seen-set so inspiration starts fresh. |
| `record_preference(observation)` | Persist a taste note (**propose-then-confirm**). |
| `get_preference_summary()` | All recorded preferences, to reload taste in a fresh session. |

---

## Design notes

- **Two-layer split (core / server).** MCP concepts never leak into `core`;
  business logic never leaks into `server`. A future GUI is a bolt-on, not a
  rewrite.
- **JSON-file persistence behind a `Repository` interface.** Simple, inspectable,
  swappable. Writes are atomic (temp file + `os.replace`) so a crash mid-write
  can't corrupt a store.
- **Lazy credentials.** The server boots and lists its tools with no network and
  no real credentials; tokens are read only when a tool calls Instagram or the
  auth middleware validates a bearer token.
- **Constructor-injected auth via a factory.** `build_server(auth_cfg)` is the
  single place a server instance is created, with auth supplied through the SDK's
  public `auth=` / `token_verifier=` parameters — no private-attribute writes.
  Passing `None` builds the unauthenticated stdio server.
- **Widget image as a data URL in `_meta`.** Only `next_inspiration` returns a
  rendered image — the one-at-a-time moment that earns the context. `get_feed`
  stays metadata-only to keep the context window light.
- **Typed errors, frozen models, strict typing.** Every external failure maps to
  a `TattooFeedError`; boundary data is validated once into immutable Pydantic v2
  values; `mypy --strict`, `ruff`, and a 90% coverage floor are enforced.

---

## Limitations (by design)

- **Inline image rendering is ChatGPT-only** — the Apps SDK widget is the one
  channel that shows the image; no other tested client displays it.
- **No video, carousels show the first image only.** Still imagery, filtered at
  the Graph-client layer.
- **Single account.** Wired to one Instagram account (`IG_USER_ID`); OAuth gates
  *who may call*, not *which account* is queried.
- **Manual token refresh.** No auto-refresh; an expired token fails with a clear
  `TokenExpiredError`.
- **Resource-server only.** The server validates tokens but does not issue them —
  it relies on an external IdP that must be configured first.
- **Widget render is human-verified.** The gate confirms the widget is registered
  and the `_meta` is present; whether the image actually paints in ChatGPT is an
  eyeball check.

---

## Attribution & copyright

Posts belong to the artists who made them. This tool is for **personal discovery
and curation**, not redistribution:

- Previews are **downscaled** copies (≤640px, EXIF stripped), never full-res.
- Every image and saved item carries the artist's **handle** and the post's
  **permalink**, so attribution travels with the content.
- Respect each artist's rights: don't repost or reuse their work without permission.

---

## Development

The full gate (all must exit 0):

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

## License

MIT — see [`LICENSE`](LICENSE).
