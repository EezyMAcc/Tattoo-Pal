"""FastMCP adapter exposing the tattoo_feed core as MCP tools.

This module is deliberately thin: every tool is a small wrapper that delegates
to a ``core`` service. No business logic lives here. Services are built lazily
on first tool use, so importing this module — and listing the tools over
stdio — needs no credentials and makes no network calls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ImageContent, TextContent
from pydantic import AnyHttpUrl

from tattoo_feed.config import load_config
from tattoo_feed.graph.client import BusinessDiscoveryClient
from tattoo_feed.imaging import fetch_preview
from tattoo_feed.models import Artist, InspirationItem, Post, Preference
from tattoo_feed.repositories.json_repo import (
    ArtistRepository,
    InspirationRepository,
    PreferenceRepository,
    SeenSetRepository,
)
from tattoo_feed.server.auth import IdpTokenVerifier, load_auth_config
from tattoo_feed.services.artists import ArtistService
from tattoo_feed.services.feed import FeedService
from tattoo_feed.services.inspiration import InspirationService
from tattoo_feed.services.preferences import PreferenceService

DATA_DIR_ENV = "TATTOO_FEED_DATA_DIR"
DEFAULT_DATA_DIR = "data"
HTTP_TIMEOUT_SECONDS = 30.0
_DEFAULT_HOST = "0.0.0.0"  # noqa: S104  in-container bind-all default
_DEFAULT_PORT = 8000


@dataclass
class TransportConfig:
    """Transport mode and network settings derived from the environment."""

    transport: Literal["stdio", "streamable-http"]
    host: str
    port: int


def resolve_transport() -> TransportConfig:
    """Map environment variables to an explicit transport configuration.

    Pure function: reads env, makes no network calls, touches no global state.
    Extracted from ``main()`` so the transport decision is unit-testable.
    """
    if os.environ.get("MCP_TRANSPORT") == "http":
        return TransportConfig(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", _DEFAULT_HOST),
            port=int(os.environ.get("MCP_PORT", str(_DEFAULT_PORT))),
        )
    return TransportConfig(transport="stdio", host=_DEFAULT_HOST, port=_DEFAULT_PORT)


mcp = FastMCP(
    "tattoo-feed",
    instructions=(
        "Browse and curate posts from a hand-picked list of Instagram tattoo "
        "artists. Use next_inspiration to discover one post at a time, "
        "save_to_inspiration to bookmark favourites, and record_preference to "
        "remember the user's taste."
    ),
)


@dataclass
class _Services:
    """Container bundling the wired-up core services and shared HTTP client."""

    artists: ArtistService
    feed: FeedService
    inspiration: InspirationService
    preferences: PreferenceService
    http: httpx.Client


_services: _Services | None = None


def _build_services() -> _Services:
    """Construct the core services from the environment (no network calls)."""
    config = load_config()
    http = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    graph = BusinessDiscoveryClient(
        config.access_token, config.ig_user_id, http_client=http
    )
    data_dir = Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))
    artist_repo = ArtistRepository(data_dir / "artists.json")
    feed = FeedService(artist_repo, graph)
    return _Services(
        artists=ArtistService(artist_repo, graph),
        feed=feed,
        inspiration=InspirationService(
            feed,
            InspirationRepository(data_dir / "inspiration.json"),
            SeenSetRepository(data_dir / "seen.json"),
        ),
        preferences=PreferenceService(
            PreferenceRepository(data_dir / "preferences.json")
        ),
        http=http,
    )


def _get_services() -> _Services:
    """Return the lazily-built services singleton."""
    global _services
    if _services is None:
        _services = _build_services()
    return _services


def _format_post(post: Post) -> str:
    """Render a post's metadata as readable text to accompany its image."""
    caption = post.caption or "(no caption)"
    return (
        f"@{post.artist_handle} — {post.timestamp:%Y-%m-%d}\n"
        f"{caption}\n"
        f"{post.permalink}"
    )


@mcp.tool()
def list_artists() -> list[Artist]:
    """List the tattoo artists currently being tracked."""
    return _get_services().artists.list_artists()


@mcp.tool()
def add_artist(handle: str) -> Artist:
    """Track a new artist by Instagram handle.

    The handle must resolve to a reachable professional (Business/Creator)
    account; otherwise a clear error is returned.
    """
    return _get_services().artists.add_artist(handle)


@mcp.tool()
def remove_artist(handle: str) -> str:
    """Stop tracking the artist with the given handle."""
    _get_services().artists.remove_artist(handle)
    return f"Stopped tracking @{handle}."


@mcp.tool()
def get_feed(limit_per_artist: int = 10) -> list[Post]:
    """Return recent posts from all tracked artists, newest first.

    Returns metadata and permalinks only (no images) to keep context light.
    """
    return _get_services().feed.get_feed(limit_per_artist)


@mcp.tool()
def next_inspiration() -> list[ImageContent | TextContent]:
    """Show one not-yet-seen post for inspiration, then mark it seen.

    Returns a rendered preview image (downscaled, EXIF-stripped) alongside the
    artist handle and permalink. Calling repeatedly walks through unseen posts;
    use reset_seen to start over.
    """
    services = _get_services()
    post = services.inspiration.next_inspiration()
    if post is None:
        return [
            TextContent(
                type="text",
                text="No new inspiration right now — call reset_seen to start over.",
            )
        ]
    preview = fetch_preview(post.image_url, services.http)
    image = Image(data=preview, format="jpeg").to_image_content()
    return [image, TextContent(type="text", text=_format_post(post))]


@mcp.tool()
def save_to_inspiration(post_id: str, notes: str | None = None) -> InspirationItem:
    """Bookmark a post (by id, from the current feed) into saved inspiration."""
    return _get_services().inspiration.save_to_inspiration(post_id, notes)


@mcp.tool()
def list_inspiration() -> list[InspirationItem]:
    """List saved inspiration items, in the order they were saved."""
    return _get_services().inspiration.list_inspiration()


@mcp.tool()
def remove_from_inspiration(post_id: str) -> str:
    """Remove a saved inspiration item by post id."""
    _get_services().inspiration.remove_from_inspiration(post_id)
    return f"Removed {post_id} from saved inspiration."


@mcp.tool()
def reset_seen() -> str:
    """Clear the seen-set so next_inspiration starts fresh."""
    _get_services().inspiration.reset_seen()
    return "Inspiration history cleared."


@mcp.tool()
def record_preference(observation: str) -> Preference:
    """Record a note about the user's tattoo taste.

    IMPORTANT: Before calling this tool, propose the observation to the user in
    your own words and obtain their explicit confirmation. Only call it once the
    user has agreed the observation is accurate. This captures taste (e.g.
    "prefers fine-line botanical work"), which is distinct from saving a
    specific image with save_to_inspiration.
    """
    return _get_services().preferences.record_preference(observation)


@mcp.tool()
def get_preference_summary() -> list[Preference]:
    """Return every recorded taste preference, so a fresh session can reload it."""
    return _get_services().preferences.get_preference_summary()


def main() -> None:  # pragma: no cover
    """Run the MCP server over stdio or HTTP (set MCP_TRANSPORT=http to use HTTP).

    When ``MCP_TRANSPORT=http`` and the ``MCP_AUTH_*`` env vars are set, the
    HTTP server is wrapped with OAuth 2.1 resource-server middleware: every
    request must carry a valid bearer token, and the
    ``/.well-known/oauth-protected-resource`` metadata document is served
    automatically by the SDK.
    """
    t = resolve_transport()
    if t.transport == "streamable-http":
        auth_cfg = load_auth_config()
        if auth_cfg is not None:
            verifier = IdpTokenVerifier(
                issuer=auth_cfg.issuer,
                jwks_url=auth_cfg.jwks_url,
                audience=auth_cfg.audience,
                http_client=httpx.AsyncClient(),
            )
            mcp.settings.auth = AuthSettings(
                issuer_url=AnyHttpUrl(auth_cfg.issuer),
                resource_server_url=AnyHttpUrl(auth_cfg.audience),
                required_scopes=auth_cfg.required_scopes or None,
            )
            mcp._token_verifier = verifier
        mcp.settings.host = t.host
        mcp.settings.port = t.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
