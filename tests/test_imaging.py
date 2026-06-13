"""Tests for preview image processing.

Exercised against the committed ``tests/fixtures/sample.jpg`` (a 1200x800
image carrying EXIF, including orientation tag 6) plus in-memory images for
edge cases. No network: downloads are mocked with respx.
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from tattoo_feed.errors import ImageProcessingError
from tattoo_feed.imaging import (
    JPEG_QUALITY,
    MAX_LONG_EDGE,
    download_image,
    fetch_preview,
    process_preview,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample.jpg"
IMAGE_URL = "https://cdn.example.com/photo.jpg"


def _encode(image: Image.Image, fmt: str = "JPEG") -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_process_preview_downscales_strips_exif_and_applies_orientation() -> None:
    out_bytes = process_preview(FIXTURE.read_bytes())
    out = Image.open(io.BytesIO(out_bytes))

    # Orientation 6 rotates the 1200x800 landscape into portrait before scaling.
    assert out.size == (427, 640)
    assert max(out.size) == MAX_LONG_EDGE
    assert out.format == "JPEG"
    # EXIF must be gone — no orientation tag, no other tags, no raw exif blob.
    assert 274 not in out.getexif()
    assert dict(out.getexif()) == {}
    assert "exif" not in out.info


def test_process_preview_never_upscales_small_images() -> None:
    small = Image.new("RGB", (320, 240), (10, 20, 30))
    out = Image.open(io.BytesIO(process_preview(_encode(small))))
    assert out.size == (320, 240)  # unchanged — never enlarged


def test_process_preview_caps_long_edge_for_portrait() -> None:
    portrait = Image.new("RGB", (800, 1600), (0, 0, 0))
    out = Image.open(io.BytesIO(process_preview(_encode(portrait))))
    assert max(out.size) == MAX_LONG_EDGE
    assert out.size == (320, 640)


def test_process_preview_flattens_rgba_to_jpeg() -> None:
    rgba = Image.new("RGBA", (500, 500), (255, 0, 0, 128))
    out = Image.open(io.BytesIO(process_preview(_encode(rgba, fmt="PNG"))))
    assert out.format == "JPEG"
    assert out.mode == "RGB"


def test_process_preview_quality_is_pinned() -> None:
    # A sanity check that the constant the spec pins is actually 85.
    assert JPEG_QUALITY == 85


def test_process_preview_rejects_non_image_bytes() -> None:
    with pytest.raises(ImageProcessingError):
        process_preview(b"this is not an image")


@respx.mock
def test_download_image_returns_bytes() -> None:
    respx.get(IMAGE_URL).mock(return_value=httpx.Response(200, content=b"rawbytes"))
    assert download_image(IMAGE_URL, httpx.Client()) == b"rawbytes"


@respx.mock
def test_download_image_maps_http_error() -> None:
    respx.get(IMAGE_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(ImageProcessingError):
        download_image(IMAGE_URL, httpx.Client())


@respx.mock
def test_download_image_maps_transport_error() -> None:
    respx.get(IMAGE_URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ImageProcessingError):
        download_image(IMAGE_URL, httpx.Client())


@respx.mock
def test_fetch_preview_downloads_then_processes() -> None:
    respx.get(IMAGE_URL).mock(
        return_value=httpx.Response(200, content=FIXTURE.read_bytes())
    )
    out = Image.open(io.BytesIO(fetch_preview(IMAGE_URL, httpx.Client())))
    assert out.format == "JPEG"
    assert max(out.size) == MAX_LONG_EDGE
