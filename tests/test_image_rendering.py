"""Structural tests for the rendered inspiration widget (Chunk 3).

These verify the *structure* of what next_inspiration returns — a data URL in
_meta that encodes a valid JPEG with long edge ≤ 640px, and a widget _meta
linking to the ui:// resource URI. They cannot verify that the image *visually
renders* in ChatGPT; that is the human eyeball check described in REVIEW.md.
"""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
from mcp.types import CallToolResult
from PIL import Image as PILImage

from tattoo_feed.models import MediaType, Post
from tattoo_feed.server import app

FIXTURE = Path(__file__).parent / "fixtures" / "sample.jpg"
TS = datetime(2024, 3, 4, tzinfo=UTC)


class _FakeInspiration:
    def __init__(self, post: Post) -> None:
        self._post = post

    def next_inspiration(self) -> Post:
        return self._post


@respx.mock
def test_next_inspiration_widget_image_is_structurally_valid() -> None:
    post = Post(
        id="p1",
        artist_handle="alice",
        media_type=MediaType.IMAGE,
        image_url="https://cdn/p1.jpg",
        permalink="https://ig/p/p1",
        timestamp=TS,
    )
    app._services = app._Services(
        artists=None,  # type: ignore[arg-type]
        feed=None,  # type: ignore[arg-type]
        inspiration=_FakeInspiration(post),  # type: ignore[arg-type]
        preferences=None,  # type: ignore[arg-type]
        http=httpx.Client(),
    )
    respx.get("https://cdn/p1.jpg").mock(
        return_value=httpx.Response(200, content=FIXTURE.read_bytes())
    )
    try:
        result = app.next_inspiration()
    finally:
        app._services = None

    assert isinstance(result, CallToolResult)
    meta = result.meta
    assert meta is not None
    # Widget link is set correctly.
    assert meta["openai/outputTemplate"] == "ui://widget/inspiration.html"

    # Image is in _meta as a data URL (not in structuredContent — keeps base64
    # out of the model's token stream, per RESEARCH.md §1.4).
    data_url: str = meta["imageDataUrl"]
    assert data_url.startswith("data:image/jpeg;base64,")  # MIME type embedded
    b64_part = data_url.split(",", 1)[1]
    raw = base64.b64decode(b64_part, validate=True)  # valid base64
    assert len(raw) > 0  # non-zero bytes
    decoded = PILImage.open(io.BytesIO(raw))
    assert decoded.format == "JPEG"  # correct format
    assert max(decoded.size) <= 640  # long edge within the pinned cap
