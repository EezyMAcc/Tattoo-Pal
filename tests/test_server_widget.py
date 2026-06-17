"""Hermetic tests for the inspiration widget resource (Chunk 3).

Verifies that the ui://widget/inspiration.html resource is registered with the
correct mimeType and contains the expected HTML/JS structure, without starting
a live server or making any network calls.
"""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from tattoo_feed.server.app import build_server

_WIDGET_URI = "ui://widget/inspiration.html"

_EXPECTED_TOOLS = {
    "list_artists",
    "add_artist",
    "remove_artist",
    "get_feed",
    "next_inspiration",
    "save_to_inspiration",
    "list_inspiration",
    "remove_from_inspiration",
    "reset_seen",
    "record_preference",
    "get_preference_summary",
}


@pytest.fixture(scope="module")
def server() -> FastMCP:
    """A no-auth server built once for the entire module."""
    return build_server(None)


def test_build_server_registers_all_tools(server: FastMCP) -> None:
    """build_server(None) registers exactly the 11 expected tools."""
    names = {t.name for t in server._tool_manager.list_tools()}
    assert names == _EXPECTED_TOOLS


async def test_widget_resource_is_registered(server: FastMCP) -> None:
    """The widget resource must be present in the resource manager."""
    resources = server._resource_manager.list_resources()
    uris = {str(r.uri) for r in resources}
    assert _WIDGET_URI in uris


async def test_widget_resource_has_mcp_app_mime_type(server: FastMCP) -> None:
    """The widget must use the exact mimeType the Apps SDK expects."""
    resources = server._resource_manager.list_resources()
    widget = next(r for r in resources if str(r.uri) == _WIDGET_URI)
    assert widget.mime_type == "text/html;profile=mcp-app"


async def test_widget_html_contains_img_tag(server: FastMCP) -> None:
    """Widget HTML must include an <img> element for the preview image."""
    resources = server._resource_manager.list_resources()
    widget = next(r for r in resources if str(r.uri) == _WIDGET_URI)
    html = await widget.read()
    assert isinstance(html, str)
    assert "<img" in html


async def test_widget_html_references_openai_bridge(server: FastMCP) -> None:
    """Widget HTML must reference window.openai to receive host-forwarded _meta."""
    resources = server._resource_manager.list_resources()
    widget = next(r for r in resources if str(r.uri) == _WIDGET_URI)
    html = await widget.read()
    assert isinstance(html, str)
    assert "window.openai" in html
