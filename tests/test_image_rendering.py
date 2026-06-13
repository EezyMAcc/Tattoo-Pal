"""Structural tests for the rendered inspiration image block (Chunk 8).

These verify the *structure* of what next_inspiration returns — valid base64,
correct MIME type, non-zero bytes, and a long edge within the pinned 640px cap.
They cannot verify that the image *visually renders* in a client; that is the
human eyeball check described in REVIEW.md.
"""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx
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
def test_next_inspiration_image_block_is_structurally_valid() -> None:
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
        blocks = app.next_inspiration()
    finally:
        app._services = None

    image = blocks[0]
    assert image.type == "image"
    assert image.mimeType == "image/jpeg"

    raw = base64.b64decode(image.data, validate=True)  # valid base64
    assert len(raw) > 0  # non-zero bytes

    decoded = PILImage.open(io.BytesIO(raw))
    assert decoded.format == "JPEG"  # correct format
    assert max(decoded.size) <= 640  # long edge within the pinned cap
