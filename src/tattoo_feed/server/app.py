"""FastMCP adapter exposing the tattoo_feed core as MCP tools.

This module is deliberately thin: every tool is a small wrapper that delegates
to a ``core`` service. No business logic lives here. Services are built lazily
on first tool use, so importing this module — and listing the tools over
stdio — needs no credentials and makes no network calls.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
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
from tattoo_feed.server.auth import AuthConfig, IdpTokenVerifier, load_auth_config
from tattoo_feed.services.artists import ArtistService
from tattoo_feed.services.feed import FeedService
from tattoo_feed.services.inspiration import InspirationService
from tattoo_feed.services.preferences import PreferenceService

DATA_DIR_ENV = "TATTOO_FEED_DATA_DIR"
DEFAULT_DATA_DIR = "data"
HTTP_TIMEOUT_SECONDS = 30.0
_DEFAULT_HOST = "0.0.0.0"  # noqa: S104  in-container bind-all default
_DEFAULT_PORT = 8000

_INSTRUCTIONS = (
    "Browse and curate posts from a hand-picked list of Instagram tattoo "
    "artists. Use next_inspiration to discover one post at a time, "
    "save_to_inspiration to bookmark favourites, and record_preference to "
    "remember the user's taste."
)

_WIDGET_URI = "ui://widget/inspiration.html"
_WIDGET_PATH = Path(__file__).parent / "widgets" / "inspiration.html"


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


def _widget_inspiration() -> str:
    """ChatGPT Apps SDK widget that renders the next_inspiration preview image."""
    return _WIDGET_PATH.read_text(encoding="utf-8")


def list_artists() -> list[Artist]:
    """List the tattoo artists currently being tracked."""
    return _get_services().artists.list_artists()


def add_artist(handle: str) -> Artist:
    """Track a new artist by Instagram handle.

    The handle must resolve to a reachable professional (Business/Creator)
    account; otherwise a clear error is returned.
    """
    return _get_services().artists.add_artist(handle)


def remove_artist(handle: str) -> str:
    """Stop tracking the artist with the given handle."""
    _get_services().artists.remove_artist(handle)
    return f"Stopped tracking @{handle}."


def get_feed(limit_per_artist: int = 10) -> list[Post]:
    """Return recent posts from all tracked artists, newest first.

    Returns metadata and permalinks only (no images) to keep context light.
    """
    return _get_services().feed.get_feed(limit_per_artist)


def next_inspiration() -> CallToolResult:
    """Show one not-yet-seen post for inspiration, then mark it seen.

    Returns a ChatGPT Apps SDK widget containing the downscaled preview image,
    artist handle, caption, and permalink. The model receives concise text to
    narrate; the image is delivered via the widget so it renders in ChatGPT.
    Calling repeatedly walks through unseen posts; use reset_seen to start over.
    """
    services = _get_services()
    post = services.inspiration.next_inspiration()
    if post is None:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=(
                        "No new inspiration right now — call reset_seen to start over."
                    ),
                )
            ],
        )
    preview = fetch_preview(post.image_url, services.http)
    # Base64-encode the preview and embed as a data URL in _meta so the host
    # forwards the image to the widget iframe without exposing it to the model.
    b64 = base64.b64encode(preview).decode()
    data_url = f"data:image/jpeg;base64,{b64}"
    return CallToolResult(
        content=[TextContent(type="text", text=_format_post(post))],
        structuredContent={
            "handle": post.artist_handle,
            "permalink": post.permalink,
            "caption": post.caption or "",
        },
        _meta={
            "openai/outputTemplate": _WIDGET_URI,
            "ui": {"resourceUri": _WIDGET_URI},
            "imageDataUrl": data_url,
            "handle": post.artist_handle,
            "caption": post.caption or "",
            "permalink": post.permalink,
        },
    )


def save_to_inspiration(post_id: str, notes: str | None = None) -> InspirationItem:
    """Bookmark a post (by id, from the current feed) into saved inspiration."""
    return _get_services().inspiration.save_to_inspiration(post_id, notes)


def list_inspiration() -> list[InspirationItem]:
    """List saved inspiration items, in the order they were saved."""
    return _get_services().inspiration.list_inspiration()


def remove_from_inspiration(post_id: str) -> str:
    """Remove a saved inspiration item by post id."""
    _get_services().inspiration.remove_from_inspiration(post_id)
    return f"Removed {post_id} from saved inspiration."


def reset_seen() -> str:
    """Clear the seen-set so next_inspiration starts fresh."""
    _get_services().inspiration.reset_seen()
    return "Inspiration history cleared."


def record_preference(observation: str) -> Preference:
    """Record a note about the user's tattoo taste.

    IMPORTANT: Before calling this tool, propose the observation to the user in
    your own words and obtain their explicit confirmation. Only call it once the
    user has agreed the observation is accurate. This captures taste (e.g.
    "prefers fine-line botanical work"), which is distinct from saving a
    specific image with save_to_inspiration.
    """
    return _get_services().preferences.record_preference(observation)


def get_preference_summary() -> list[Preference]:
    """Return every recorded taste preference, so a fresh session can reload it."""
    return _get_services().preferences.get_preference_summary()


def _public_host(audience: str) -> str:
    """Return the bare ``host[:port]`` from the resource-server audience URL.

    The audience (``MCP_AUTH_AUDIENCE``) is the canonical public URL of this
    server, e.g. ``https://my-name.ngrok-free.dev/``. Behind a tunnel the
    inbound ``Host`` header carries exactly this netloc, so it is the value that
    must appear on the DNS-rebinding allow-list (see ``_allow_public_host``).

    Args:
        audience: The resource-server audience URL.

    Returns:
        The URL's network location, e.g. ``my-name.ngrok-free.dev``.
    """
    return urlparse(audience).netloc


def _allow_public_host(server: FastMCP, audience: str) -> None:
    """Re-point the SDK's DNS-rebinding guard at this server's real public host.

    ``FastMCP`` derives ``settings.transport_security`` from its ``host``
    constructor argument (default ``127.0.0.1``), freezing the allowed-``Host``
    list to localhost at construction time; the later ``settings.host`` override
    in :func:`main` does not re-derive it. Behind a tunnel every request then
    arrives with the public ``Host`` and is refused with ``421``. Reassigning
    ``transport_security`` after construction *is* honoured, because the
    middleware reads it per-request.

    This is hygiene, not a load-bearing control: this server is public and
    OAuth-gated, so DNS rebinding (a localhost-targeting browser attack) cannot
    reach it. Keeping the guard on but scoped to the real host documents the
    server's identity and fails safe if a browser-facing surface is added later.
    Localhost is retained so in-container and health-check access still work.

    Args:
        server: The constructed FastMCP server to reconfigure.
        audience: The resource-server audience URL the public host derives from.
    """
    host = _public_host(audience)
    server.settings.transport_security = TransportSecuritySettings(
        allowed_hosts=[host, f"{host}:*", "127.0.0.1:*", "localhost:*"],
        allowed_origins=[f"https://{host}"],
    )


def build_server(auth_cfg: AuthConfig | None) -> FastMCP:
    """Build a configured FastMCP server instance.

    Constructs the server with or without OAuth authentication, injects auth
    exclusively through public constructor parameters (never private attribute
    writes), registers the widget resource and all 11 tools, and returns the
    ready-to-run instance. When auth is configured, the DNS-rebinding allow-list
    is re-pointed at the public host (see :func:`_allow_public_host`).

    Args:
        auth_cfg: Identity-provider settings for resource-server validation.
            Pass ``None`` for unauthenticated stdio / local-dev use.

    Returns:
        A :class:`~mcp.server.fastmcp.FastMCP` instance with all tools and the
        widget resource registered.
    """
    if auth_cfg is not None:
        server = FastMCP(
            "tattoo-feed",
            instructions=_INSTRUCTIONS,
            auth=AuthSettings(
                issuer_url=AnyHttpUrl(auth_cfg.issuer),
                resource_server_url=AnyHttpUrl(auth_cfg.audience),
                required_scopes=auth_cfg.required_scopes or None,
            ),
            token_verifier=IdpTokenVerifier(
                issuer=auth_cfg.issuer,
                jwks_url=auth_cfg.jwks_url,
                audience=auth_cfg.audience,
                http_client=httpx.AsyncClient(),
            ),
        )
        _allow_public_host(server, auth_cfg.audience)
    else:
        server = FastMCP("tattoo-feed", instructions=_INSTRUCTIONS)

    server.resource(_WIDGET_URI, mime_type="text/html;profile=mcp-app")(
        _widget_inspiration
    )
    server.tool()(list_artists)
    server.tool()(add_artist)
    server.tool()(remove_artist)
    server.tool()(get_feed)
    # Declare the widget on the tool *descriptor* (not just the call result) so
    # the Apps SDK host knows to render the inspiration widget for this tool's
    # output (Phase2_RESEARCH §1.2). Without descriptor meta the host falls back
    # to plain text and the preview image never renders.
    server.tool(
        meta={
            "openai/outputTemplate": _WIDGET_URI,
            "ui": {"resourceUri": _WIDGET_URI},
        }
    )(next_inspiration)
    server.tool()(save_to_inspiration)
    server.tool()(list_inspiration)
    server.tool()(remove_from_inspiration)
    server.tool()(reset_seen)
    server.tool()(record_preference)
    server.tool()(get_preference_summary)

    return server


def run_server(transport: TransportConfig) -> None:
    """Build, configure, and run the MCP server for the given transport.

    Extracted from :func:`main` so the transport dispatch — server
    construction, host/port binding, and the HTTP-vs-stdio branch — is
    exercised by the gate (the tests patch ``FastMCP.run`` to a no-op), leaving
    only the genuinely un-runnable blocking ``run()`` call behind the pragma in
    :func:`main`'s thin entry glue.

    When ``transport`` is streamable-http and the ``MCP_AUTH_*`` env vars are
    set, the server is wrapped with OAuth 2.1 resource-server middleware: every
    request must carry a valid bearer token, and the
    ``/.well-known/oauth-protected-resource`` metadata document is served
    automatically by the SDK.

    Args:
        transport: The resolved transport configuration.
    """
    if transport.transport == "streamable-http":
        server = build_server(load_auth_config())
        server.settings.host = transport.host
        server.settings.port = transport.port
        server.run(transport="streamable-http")
    else:
        build_server(None).run()


def main() -> None:  # pragma: no cover
    """Entry point: resolve the transport from the environment and run.

    The only un-coverable lines in this module: a single dispatch to
    :func:`run_server` (itself tested) followed by ``run()`` blocking forever.
    """
    run_server(resolve_transport())


if __name__ == "__main__":  # pragma: no cover
    main()
