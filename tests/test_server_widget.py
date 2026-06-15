"""Hermetic tests for the inspiration widget resource (Chunk 3).

Verifies that the ui://widget/inspiration.html resource is registered with the
correct mimeType and contains the expected HTML/JS structure, without starting
a live server or making any network calls.
"""

from __future__ import annotations

from tattoo_feed.server import app

_WIDGET_URI = "ui://widget/inspiration.html"


async def test_widget_resource_is_registered() -> None:
    """The widget resource must be present in the resource manager."""
    resources = app.mcp._resource_manager.list_resources()
    uris = {str(r.uri) for r in resources}
    assert _WIDGET_URI in uris


async def test_widget_resource_has_mcp_app_mime_type() -> None:
    """The widget must use the exact mimeType the Apps SDK expects."""
    resources = app.mcp._resource_manager.list_resources()
    widget = next(r for r in resources if str(r.uri) == _WIDGET_URI)
    assert widget.mime_type == "text/html;profile=mcp-app"


async def test_widget_html_contains_img_tag() -> None:
    """Widget HTML must include an <img> element for the preview image."""
    resources = app.mcp._resource_manager.list_resources()
    widget = next(r for r in resources if str(r.uri) == _WIDGET_URI)
    html = await widget.read()
    assert isinstance(html, str)
    assert "<img" in html


async def test_widget_html_references_openai_bridge() -> None:
    """Widget HTML must reference window.openai to receive host-forwarded _meta."""
    resources = app.mcp._resource_manager.list_resources()
    widget = next(r for r in resources if str(r.uri) == _WIDGET_URI)
    html = await widget.read()
    assert isinstance(html, str)
    assert "window.openai" in html
