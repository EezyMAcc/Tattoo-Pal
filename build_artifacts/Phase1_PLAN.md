# PLAN.md — Tattoo Feed MCP Server

The build plan. Work the chunks in order. Each chunk lists its deliverables, its
gate, and a one-line success condition. The gate is always the canonical gate in
`CLAUDE.md` §4; the success condition is the *additional* truth that must hold.

---

## 1. Architecture & layout

Two layers. `core` is pure logic and knows nothing about MCP. `server` is a thin
FastMCP adapter. A future GUI will import `core` directly.

```
src/tattoo_feed/
  __init__.py
  config.py              # loads IG_ACCESS_TOKEN, IG_USER_ID from env (lazy)
  models.py              # Pydantic v2: Post, Artist, InspirationItem, Preference
  errors.py              # typed error hierarchy
  imaging.py             # downscale + EXIF strip (Pillow)
  repositories/
    __init__.py
    base.py              # Repository protocol (ABC)
    json_repo.py         # JSON-file repositories + atomic writes
  graph/
    __init__.py
    client.py            # Business Discovery client (httpx): fetch + validate
  services/
    __init__.py
    feed.py              # FeedService
    artists.py           # ArtistService
    inspiration.py       # InspirationService
    preferences.py       # PreferenceService
  server/
    __init__.py
    app.py               # FastMCP server: tool defs + entrypoint (main)
tests/                   # mirrors src/ ; respx for all HTTP
  fixtures/              # sample API payloads + one sample JPEG
data/                    # gitignored runtime JSON stores (created at runtime)
```

---

## 2. Pinned decisions (do not re-litigate)

- **Stack:** Python 3.12, `uv`, official `mcp` SDK (FastMCP), **stdio** transport.
- **Persistence:** JSON files behind a `Repository` interface. Stores: artists,
  inspiration items, preferences, seen-set. Atomic writes (write temp + rename).
- **Hermetic tests:** all Instagram HTTP mocked with `respx`. One live test
  guarded by `RUN_LIVE=1`, never run in the loop.
- **Credentials:** `IG_ACCESS_TOKEN`, `IG_USER_ID` from env, loaded lazily (the
  server boots and lists tools with no network and no real creds). Never
  committed; documented in `.env.example` + README.
- **Token expiry:** raise `TokenExpiredError` with a clear "refresh your token"
  message. No auto-refresh.
- **Videos:** filtered out entirely at the Graph client layer (`media_type ==
  "VIDEO"` never enters feed, inspiration, or stores).
- **Carousels:** first child image only. Multi-image expansion is phase 2.
- **Feed:** default **10** posts per artist; merged across all artists; sorted
  **newest-first** by timestamp; one failing artist is skipped (logged + noted),
  never sinks the whole feed.
- **Inspiration:** `next_inspiration` returns one **not-yet-seen** post; a
  seen-set in core prevents repeats; resettable via `reset_seen`.
- **Saved inspiration order:** preserved in save order. Each saved item stores
  the artist **handle** (for the phase-2 GUI attribution bubble), permalink,
  post id, timestamp, and optional notes.
- **Preferences:** `record_preference` is **propose-then-confirm** (see
  `CLAUDE.md` §10). Distinct from saving images: preferences capture *taste*,
  saved items capture *specific images*.
- **Images returned to the client:** **only `next_inspiration` returns a rendered
  image block** (one at a time — the conversational experience). `get_feed`
  returns metadata + permalinks only, to keep context light. (GUI renders feed
  images later, direct from core.)
- **Image preview spec (deterministic):** max **640px on the long edge**,
  preserve aspect ratio, **never upscale**, JPEG **quality 85**, **strip EXIF**.
- **Coverage:** `--cov-fail-under=90` across `src/tattoo_feed`. Only
  `server/app.py:main()` may carry `# pragma: no cover`.

---

## 3. Approved dependencies (exact-pin these; no others)

Runtime: `mcp`, `httpx`, `pydantic`, `Pillow`.
Dev: `pytest`, `pytest-cov`, `pytest-asyncio`, `respx`, `ruff`, `mypy`.

Pin each to its current latest stable version at install time and commit
`uv.lock`. Adding anything else → stop, record in `BLOCKERS.md`.

---

## 4. Data model (`models.py`)

- **Post** — `id`, `artist_handle`, `caption | None`, `media_type`
  (`IMAGE | CAROUSEL_ALBUM`), `image_url`, `permalink`, `timestamp` (datetime).
- **Artist** — `handle`, `ig_user_id | None`, `added_at`.
- **InspirationItem** — `post_id`, `artist_handle`, `image_url`, `permalink`,
  `timestamp`, `notes | None`, `saved_at`.
- **Preference** — `id`, `observation` (str), `created_at`.

---

## 5. Typed errors (`errors.py`)

`TattooFeedError` (base) →
`TokenExpiredError`, `AccountNotFoundError`, `NotAProfessionalAccountError`,
`RateLimitedError`, `RepositoryError`, `ImageProcessingError`.

Every external failure maps to one of these. No bare exceptions cross a
boundary.

---

## 6. Tool contracts (the MCP surface, exposed in `server/app.py`)

Each is a thin wrapper over a `core` service. Docstrings become the client-
visible descriptions, so write them carefully.

- `list_artists() -> list[Artist]` — the tracked artists.
- `add_artist(handle: str) -> Artist` — validates the handle resolves to a
  reachable **professional** account (via the Graph client) before saving;
  raises `AccountNotFoundError` / `NotAProfessionalAccountError` otherwise.
- `remove_artist(handle: str) -> None` — removes from the list.
- `get_feed(limit_per_artist: int = 10) -> list[Post]` — merged, newest-first,
  per-artist errors skipped + noted. Metadata only (no image blocks).
- `next_inspiration() -> (image block + Post metadata)` — one not-yet-seen post,
  marks it seen, returns a **rendered downscaled image** plus handle + permalink.
- `save_to_inspiration(post_id: str, notes: str | None = None) -> InspirationItem`
  — bookmarks the post into the saved store.
- `list_inspiration() -> list[InspirationItem]` — the saved set (save order).
- `remove_from_inspiration(post_id: str) -> None` — remove a saved item.
- `reset_seen() -> None` — clears the seen-set so inspiration starts fresh.
- `record_preference(observation: str) -> Preference` — persists a taste note.
  **Description must instruct propose-then-confirm.**
- `get_preference_summary() -> list[Preference]` — all preferences, so a fresh
  session can reload the user's taste.

---

## 7. Chunks

### Chunk 0 — Scaffold & toolchain
**Deliverables:** `pyproject.toml` (deps pinned, ruff/mypy/pytest/coverage
config), `uv.lock`, `src/` + `tests/` skeleton, `.gitignore` (ignores `.env`,
`data/`), `.env.example`, `LICENSE` (MIT), `README.md` skeleton,
`.github/workflows/ci.yml` mirroring the gate.
**Gate:** canonical gate passes on the empty-but-typed skeleton.
**Success condition:** `uv run` works in the container and all four gate
commands exit 0.

### Chunk 1 — Domain models & errors
**Deliverables:** `models.py`, `errors.py`, full unit tests.
**Success condition:** models validate/round-trip and the error hierarchy is
covered ≥90%.

### Chunk 2 — Repository layer
**Deliverables:** `repositories/base.py` (ABC), `repositories/json_repo.py`
(artists, inspiration, preferences, seen-set; atomic writes), tests using
`tmp_path`.
**Success condition:** CRUD + persistence + atomicity tested; no real home-dir
writes in tests.

### Chunk 3 — Graph client (mocked)
**Deliverables:** `graph/client.py` — `validate_account(handle)` and
`fetch_recent_media(handle, limit)`; **filters out videos**; **carousel →
first image**; TTL cache; 429 backoff; maps failures to typed errors
(incl. `TokenExpiredError`). All tested with `respx`.
**Success condition:** every branch (video filter, carousel, not-found,
not-professional, expired token, rate-limit) covered with mocks; zero live
calls.

### Chunk 4 — Image processing
**Deliverables:** `imaging.py` — fetch bytes (mocked in tests) + downscale to
the pinned spec (640px long edge, no upscale, JPEG q85, EXIF stripped). Test
against `tests/fixtures` sample JPEG.
**Success condition:** output dimensions, format, and EXIF-absence asserted
exactly against a known input.

### Chunk 5 — Core services
**Deliverables:** `services/feed.py`, `artists.py`, `inspiration.py`,
`preferences.py`, wiring repositories + graph client. Implements all behaviours
in §6. Unit-tested with mocked client + `tmp_path` repositories.
**Success condition:** feed merge/sort/error-isolation, add-artist validation,
seen-set behaviour, save/list/remove, preference record/summary all tested ≥90%.

### Chunk 6 — MCP server (text-only) + boot test
**Deliverables:** `server/app.py` — FastMCP server exposing all §6 tools wired
to services; lazy config; `main()` stdio entrypoint. `next_inspiration` returns
metadata + a placeholder for the image (real image deferred to Chunk 8).
`tests/test_server_boot.py` starts the server over stdio with dummy env and
asserts the full expected tool set.
**Success condition:** server boots with no network/no real creds and lists
every tool in §6.

### Chunk 7 — Docs & polish
**Deliverables:** complete `README.md` — setup, env vars, run in/out of Docker,
**design decisions**, **limitations** (videos skipped, carousel first-image,
manual token refresh, preview sizing, propose-then-confirm), and an
**attribution/copyright note** (previews are downscaled; handle + permalink
credit every image). Docstrings complete across the codebase.
**Success condition:** gate green; README covers every pinned decision.

### Chunk 8 — Image rendering (FINAL, REVIEW-FLAGGED)
**Deliverables:** wire `imaging.py` into `next_inspiration` so it returns a real
MCP **image content block** (base64) alongside metadata. Structural tests only:
valid base64, correct MIME, non-zero bytes, dimensions ≤640 on long edge.
**Success condition:** structural tests pass — then **STOP** and write
`REVIEW.md`. Do not declare the project verified: whether images *visually
render* is a human eyeball check (see `CLAUDE.md` §11).

---

## 8. Final state to leave behind

Branch `feat/auto-build` with one green commit per chunk, a clean working tree,
a `REVIEW.md` describing the morning verification steps, and — only if a gate
blocked — a `BLOCKERS.md`. Nothing on `main`.
