# Tattoo Feed

An MCP (Model Context Protocol) server that lets an LLM client browse and curate
posts from a hand-picked list of Instagram tattoo artists, via Instagram's
Business Discovery API.

> Skeleton README — fleshed out in Chunk 7. See `PLAN.md` for the build plan and
> `CLAUDE.md` for the operating rules.

## Status

Work in progress, built chunk-by-chunk on the `feat/auto-build` branch.

## Layout

- `core` (`src/tattoo_feed/` minus `server/`) — pure domain logic: models,
  errors, repositories, the Graph client, imaging, and services.
- `server` (`src/tattoo_feed/server/`) — a thin FastMCP adapter exposing the
  core as MCP tools.

## Development

```bash
uv sync
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -q --cov=src/tattoo_feed --cov-report=term-missing --cov-fail-under=90
```
