# Tattoo Feed

An **MCP (Model Context Protocol) server** that lets an LLM client browse and
curate posts from a hand-picked list of Instagram tattoo artists, via
Instagram's **Business Discovery** API.

You point it at the artists you follow, and from your chat client you can pull a
merged feed, discover one post at a time, bookmark the ones you like, and record
notes about your taste so a future session remembers them.

**Phase 2 adds a remote, OAuth-protected mode** so the server can be connected
to **ChatGPT** via a custom connector. `next_inspiration` now returns a ChatGPT
Apps SDK **widget** that renders the preview image inline — native MCP image
blocks are not rendered by ChatGPT, hence the widget.

---

## Architecture

A deliberate two-layer split so a future GUI can reuse the logic without a
rewrite:

- **`core`** (`src/tattoo_feed/` excluding `server/`) — all real logic: domain
  models, typed errors, JSON-file repositories, the Graph API client, image
  processing, and the services that orchestrate them. Knows nothing about MCP.
- **`server`** (`src/tattoo_feed/server/`) — a thin
  [FastMCP](https://github.com/modelcontextprotocol/python-sdk) adapter that
  exposes `core` as MCP tools. Holds no business logic.

```
src/tattoo_feed/
  config.py            # lazy env config (IG_ACCESS_TOKEN, IG_USER_ID)
  errors.py            # typed error hierarchy (TattooFeedError and subclasses)
  models.py            # Pydantic v2 value objects
  imaging.py           # preview downscale + EXIF strip (≤640px JPEG)
  repositories/        # Repository ABC + JSON-file stores (atomic writes)
  graph/client.py      # Business Discovery client
  services/            # FeedService, ArtistService, InspirationService, PreferenceService
  server/app.py        # FastMCP tools + stdio/HTTP entrypoint
  server/auth.py       # OAuth 2.1 JWT verifier (resource-server side)
  server/widgets/      # Apps SDK widget HTML served as ui:// MCP resource
```

### Transport modes

| Mode | When | Who can connect |
|------|------|-----------------|
| **stdio** (default) | Local use | Claude Desktop, any local MCP client |
| **HTTP** (`MCP_TRANSPORT=http`) | Remote/container | ChatGPT, any remote MCP client |

In HTTP mode the server acts as an **OAuth 2.1 resource server**: every request
must carry a valid bearer token issued by your identity provider.  An
unauthenticated request receives `401` with a `WWW-Authenticate: Bearer
resource_metadata=...` header per RFC 9728; the ChatGPT connector follows this
to discover and complete the login flow automatically.

---

## Setup

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                       # create the venv and install pinned deps
cp .env.example .env          # then edit .env with your real credentials
```

### Environment variables

#### Always required (Instagram credentials)

| Variable | Meaning |
|---|---|
| `IG_ACCESS_TOKEN` | A long-lived Instagram Graph API access token. |
| `IG_USER_ID` | The Instagram Business/Creator account id that owns the token. |
| `TATTOO_FEED_DATA_DIR` | Optional. Where the JSON stores live (default `./data`). |

#### Required for HTTP / ChatGPT mode (OAuth resource-server config)

| Variable | Meaning |
|---|---|
| `MCP_AUTH_ISSUER` | Issuer URL of your IdP — must exactly match the `iss` claim. |
| `MCP_AUTH_JWKS_URL` | JWKS endpoint used to verify JWT signatures. |
| `MCP_AUTH_AUDIENCE` | Canonical public URL of this server — the RFC 8707 audience binding. |
| `MCP_AUTH_REQUIRED_SCOPES` | Comma-separated required scopes (e.g. `mcp:read`). |
| `NGROK_AUTHTOKEN` | ngrok auth token for TLS ingress. |

`.env` is gitignored and must never be committed. Only `.env.example` (with
placeholders) is in the repo.

Getting Instagram credentials is a one-time manual step on Meta's side: create
a Meta app, connect an Instagram Business/Creator account, and mint a
**long-lived** access token with Business Discovery permission.

---

## Running

### Locally (stdio — Claude Desktop, local clients)

```bash
uv run python -m tattoo_feed.server.app
```

The server speaks the MCP stdio protocol. For Claude Desktop, add to its config:

```json
{
  "mcpServers": {
    "tattoo-feed": {
      "command": "uv",
      "args": ["run", "python", "-m", "tattoo_feed.server.app"],
      "cwd": "/absolute/path/to/tattoo-feed",
      "env": {
        "IG_ACCESS_TOKEN": "your-token",
        "IG_USER_ID": "your-business-user-id"
      }
    }
  }
}
```

### Remote (HTTP + OAuth + ngrok — ChatGPT connector)

The quickest path is Docker Compose, which starts the server and the ngrok
tunnel together:

```bash
cp .env.example .env          # fill in all values, including MCP_AUTH_* and NGROK_AUTHTOKEN
./scripts/run-server.sh       # builds the image and starts server + ngrok
```

After startup:
1. Open the ngrok inspector at `http://localhost:4040` to find the public URL.
2. In ChatGPT, add a **custom connector**:
   - URL: `https://<your-ngrok-url>/mcp`
   - Authentication: **OAuth**
3. ChatGPT will walk through OAuth discovery and a browser login against your IdP.

#### Identity provider (you choose)

The server is IdP-agnostic — it only needs an issuer that supports OAuth 2.1
with PKCE, RFC 8414/OIDC metadata discovery, RFC 8707 `resource` indicator, and
Client ID Metadata Documents.  **Auth0** has a documented walkthrough for
exactly this setup:
<https://auth0.com/blog/add-remote-mcp-server-chatgpt/>.  Alternatives:
Stytch, WorkOS, Descope.

Configure your IdP to include the server's public URL (`MCP_AUTH_AUDIENCE`) as
the audience in the tokens it issues, then set that same URL as the resource
identifier in the ChatGPT connector.

#### Stable domain (recommended)

A new ngrok URL is generated each restart, which breaks the ChatGPT connector
URL. Reserve a stable domain at <https://dashboard.ngrok.com/domains>, set
`NGROK_DOMAIN` in `.env`, and add `--domain=${NGROK_DOMAIN}` to the ngrok
command in `docker-compose.yml`.

### In the dev container (gate / CI)

A dev image (`Dockerfile`) bundles Python, `uv`, Node, and the toolchain:

```bash
docker build -t tattoo-feed-dev .
./run-loop.sh        # mounts $PWD to /workspace, nothing else on your machine
```

---

## The tools (MCP surface)

| Tool | What it does |
|------|--------------|
| `list_artists` | List tracked artists. |
| `add_artist(handle)` | Validate the handle is a reachable **professional** account, then track it. |
| `remove_artist(handle)` | Stop tracking a handle. |
| `get_feed(limit_per_artist=10)` | Merged, newest-first feed. Metadata + permalinks only (no images). |
| `next_inspiration()` | One **not-yet-seen** post, marked seen. Returns an Apps SDK widget with the preview image in ChatGPT; a text fallback in other clients. |
| `save_to_inspiration(post_id, notes=None)` | Bookmark a post into the saved collection. |
| `list_inspiration()` | The saved collection, in save order. |
| `remove_from_inspiration(post_id)` | Remove a saved item. |
| `reset_seen()` | Clear the seen-set so inspiration starts fresh. |
| `record_preference(observation)` | Persist a taste note (**propose-then-confirm**, see below). |
| `get_preference_summary()` | All recorded preferences, to reload taste in a fresh session. |

### How `next_inspiration` surfaces in ChatGPT

The tool returns three channels (per the Apps SDK spec):

- **`structuredContent`** — handle, permalink, caption — what the model narrates.
  No base64.
- **`content`** — plain-text fallback for non-ChatGPT clients.
- **widget** — an HTML/JS component registered at `ui://widget/inspiration.html`
  (mimeType `text/html;profile=mcp-app`) that the ChatGPT host renders inline.
  The preview image travels as a data URL in `_meta` so it reaches the widget
  without passing through the model's context window.

---

## Design decisions

- **Two-layer split (core / server).** MCP concepts never leak into `core`;
  business logic never leaks into `server`. This is what makes a future GUI a
  bolt-on rather than a rewrite.
- **JSON-file persistence behind a `Repository` interface.** Simple,
  inspectable, and swappable. Writes are **atomic** (temp file + `os.replace`)
  so a crash mid-write can never corrupt a store.
- **Pydantic v2 frozen models** for everything crossing a boundary, so external
  data is validated once and treated as immutable values thereafter.
- **Typed error hierarchy** (`TattooFeedError` and friends). Every external
  failure maps to a typed error; nothing raises bare exceptions across a
  boundary, so the client always gets a readable message instead of a stack
  trace.
- **Lazy credentials.** The server boots and lists its tools with no network and
  no real credentials; tokens are only read when a tool actually calls Instagram
  or when the auth middleware validates a bearer token.
- **Hermetic tests.** All Instagram HTTP is mocked with `respx`; JWKS is mocked
  with test-generated RSA keypairs; there are zero live network calls in the
  test suite. (`mypy --strict`, `ruff`, and a 90% coverage floor are enforced.)
- **Widget image as data URL in `_meta`.** The ≤640px preview is base64-encoded
  into `_meta.imageDataUrl`. The ChatGPT host forwards `_meta` to the widget
  iframe without exposing it to the model, so the base64 blob never inflates the
  model's context window.
- **Images only where they earn their context.** Only `next_inspiration` returns
  a rendered image — the one-at-a-time conversational moment. `get_feed` stays
  metadata-only to keep the context window light.

---

## Limitations (by design)

- **No video.** Video posts are filtered out entirely at the Graph-client layer
  and never enter the feed, inspiration, or stores.
- **Carousels show the first image only.** Multi-image expansion is out of scope.
- **Manual token refresh.** There is no automatic token refresh. When the token
  expires, tools fail with a clear `TokenExpiredError` telling you to mint a new
  long-lived token and update `IG_ACCESS_TOKEN`.
- **Preview sizing is fixed.** Previews are capped at **640px on the long edge**,
  aspect ratio preserved, never upscaled, re-encoded as **JPEG quality 85**.
- **`record_preference` is propose-then-confirm.** The tool persists whatever it
  is given; the *discipline* of proposing the observation to you and getting your
  explicit confirmation **before** the tool is called lives in the tool's
  description, so the calling assistant honours it.
- **No write access to Instagram.** No posting, commenting, or messaging — this
  is strictly read-and-curate.
- **Single account.** The server is wired to one Instagram Business/Creator
  account (set via `IG_USER_ID`). OAuth gates *who may call*, not *which account*
  is queried. Multi-account support would require per-session service
  construction, which is out of scope.
- **IdP dependency.** The server relies on an external identity provider for
  token issuance. The IdP must be set up and configured before the ChatGPT
  connector will complete its OAuth login.
- **Widget visual verification is manual.** The automated gate confirms the
  widget resource is registered and the `_meta` fields are present, but whether
  the image actually renders in ChatGPT's UI requires a human eyeball check (see
  `REVIEW.md`).
- **No self-hosted authorization server.** The server acts as a resource server
  only; it does not issue tokens. Use Auth0, Stytch, WorkOS, Descope, or another
  IdP that supports the OAuth 2.1 + PKCE + RFC 8707 flow.

---

## Attribution & copyright

Posts belong to the artists who made them. This tool is for **personal
discovery and curation**, not redistribution:

- Previews are **downscaled** copies (≤640px, EXIF stripped), not
  full-resolution downloads.
- Every image and saved item carries the artist's **handle** and the post's
  **permalink**, so attribution travels with the content and you can always open
  the original on Instagram.
- Respect each artist's rights: don't repost or reuse their work without
  permission.

---

## Development

The full gate (must all exit 0):

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```

## License

MIT — see [`LICENSE`](LICENSE).
