# Tattoo Feed

An **MCP (Model Context Protocol) server** that lets an LLM client (e.g. Claude
Desktop) browse and curate posts from a hand-picked list of Instagram tattoo
artists, via Instagram's **Business Discovery** API.

You point it at the artists you follow, and from your chat client you can pull a
merged feed, discover one post at a time, bookmark the ones you like, and record
notes about your taste so a future session remembers them.

---

## Architecture

A deliberate two-layer split so a future GUI can reuse the logic without a
rewrite:

- **`core`** (`src/tattoo_feed/` excluding `server/`) — all real logic: domain
  models, typed errors, JSON-file repositories, the Graph API client, image
  processing, and the services that orchestrate them. Knows nothing about MCP.
- **`server`** (`src/tattoo_feed/server/`) — a thin [FastMCP](https://github.com/modelcontextprotocol/python-sdk)
  adapter that exposes `core` as MCP tools. Holds no business logic.

```
src/tattoo_feed/
  config.py            # lazy env config (IG_ACCESS_TOKEN, IG_USER_ID)
  models.py            # Pydantic v2 value objects
  errors.py            # typed error hierarchy
  imaging.py           # preview downscale + EXIF strip
  repositories/        # Repository ABC + JSON-file stores (atomic writes)
  graph/client.py      # Business Discovery client
  services/            # FeedService, ArtistService, InspirationService, PreferenceService
  server/app.py        # FastMCP tools + stdio entrypoint
```

---

## Setup

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                       # create the venv and install pinned deps
cp .env.example .env          # then edit .env with your real credentials
```

### Environment variables

| Variable           | Meaning                                                        |
|--------------------|----------------------------------------------------------------|
| `IG_ACCESS_TOKEN`  | A long-lived Instagram Graph API access token.                 |
| `IG_USER_ID`       | The Instagram Business/Creator account id that owns the token. |
| `TATTOO_FEED_DATA_DIR` | Optional. Where the JSON stores live (default `./data`).   |

`.env` is gitignored and must never be committed. Only `.env.example` (with
placeholders) is in the repo.

Getting credentials is a one-time manual step on Meta's side: create a Meta app,
connect an Instagram Business/Creator account, and mint a **long-lived** access
token with Business Discovery permission. Both the querying account and the
artists you look up must be professional accounts.

---

## Running

### Locally (stdio)

```bash
uv run python -m tattoo_feed.server.app
```

The server speaks the MCP stdio protocol, so you normally don't run it by hand —
you register it with an MCP client. For Claude Desktop, add to its config:

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

### In Docker

A dev image (`Dockerfile`) bundles Python, `uv`, Node, and the toolchain. Build
and open a shell with **only this folder** mounted to `/workspace`:

```bash
docker build -t tattoo-feed-dev .
./run-loop.sh        # mounts $PWD to /workspace, nothing else on your machine
```

Inside the container you have the full gate and can run the server exactly as
above. The volume mount means anything written under `/workspace` lands back in
this folder on your host.

---

## The tools (MCP surface)

| Tool | What it does |
|------|--------------|
| `list_artists` | List tracked artists. |
| `add_artist(handle)` | Validate the handle is a reachable **professional** account, then track it. |
| `remove_artist(handle)` | Stop tracking a handle. |
| `get_feed(limit_per_artist=10)` | Merged, newest-first feed. Metadata + permalinks only (no images). |
| `next_inspiration()` | One **not-yet-seen** post, marked seen, with a rendered preview image. |
| `save_to_inspiration(post_id, notes=None)` | Bookmark a post into the saved collection. |
| `list_inspiration()` | The saved collection, in save order. |
| `remove_from_inspiration(post_id)` | Remove a saved item. |
| `reset_seen()` | Clear the seen-set so inspiration starts fresh. |
| `record_preference(observation)` | Persist a taste note (**propose-then-confirm**, see below). |
| `get_preference_summary()` | All recorded preferences, to reload taste in a fresh session. |

---

## Design decisions

- **Two-layer split (core / server).** MCP concepts never leak into `core`;
  business logic never leaks into `server`. This is what makes a phase-2 GUI a
  bolt-on rather than a rewrite.
- **JSON-file persistence behind a `Repository` interface.** Simple, inspectable,
  and swappable. Writes are **atomic** (temp file + `os.replace`) so a crash
  mid-write can never corrupt a store.
- **Pydantic v2 frozen models** for everything crossing a boundary, so external
  data is validated once and treated as immutable values thereafter.
- **Typed error hierarchy** (`TattooFeedError` and friends). Every external
  failure maps to a typed error; nothing raises bare exceptions across a
  boundary, so the client always gets a readable message instead of a stack
  trace.
- **Lazy credentials.** The server boots and lists its tools with no network and
  no real credentials; the token is only read when a tool actually calls
  Instagram.
- **Hermetic tests.** All Instagram HTTP is mocked with `respx`; there are zero
  live network calls in the test suite. (`mypy --strict`, `ruff`, and a 90%
  coverage floor are enforced.)
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

---

## Attribution & copyright

Posts belong to the artists who made them. This tool is for **personal
discovery and curation**, not redistribution:

- Previews are **downscaled** copies (≤640px, EXIF stripped), not full-resolution
  downloads.
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
