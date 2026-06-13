"""Preview image processing.

Turns a raw Instagram image into a lightweight, privacy-respecting preview to
return to the client. The transform is deterministic and pinned (see
``PLAN.md`` §2):

* longest edge capped at **640px**, aspect ratio preserved, **never upscaled**;
* re-encoded as **JPEG quality 85**;
* **EXIF stripped** — but orientation is *applied first* so a photo shot in
  portrait does not come back sideways.

Downloading is done through an injected :class:`httpx.Client` so tests mock it
with ``respx`` and never hit the network.
"""

from __future__ import annotations

import io
import logging

import httpx
from PIL import Image, ImageOps

from tattoo_feed.errors import ImageProcessingError

logger = logging.getLogger(__name__)

MAX_LONG_EDGE = 640
JPEG_QUALITY = 85


def download_image(url: str, http_client: httpx.Client) -> bytes:
    """Download the raw bytes of an image.

    Args:
        url: The image URL to fetch.
        http_client: The HTTP client to use (injected for testability).

    Returns:
        The raw response body.

    Raises:
        ImageProcessingError: If the download fails or returns an error status.
    """
    try:
        response = http_client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ImageProcessingError(
            f"could not download image from {url}: {exc}"
        ) from exc
    return response.content


def process_preview(data: bytes) -> bytes:
    """Downscale and re-encode image bytes to the pinned preview spec.

    Args:
        data: Raw bytes of a source image.

    Returns:
        JPEG bytes: <=640px on the long edge, EXIF-stripped, quality 85.

    Raises:
        ImageProcessingError: If the bytes are not a decodable image.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            # Bake in EXIF orientation, then drop EXIF entirely by re-encoding.
            oriented = ImageOps.exif_transpose(image) or image
            # Flatten to RGB so JPEG encoding is always valid (e.g. PNG/alpha).
            rgb = oriented.convert("RGB")
            # thumbnail() preserves aspect ratio and never enlarges the image.
            rgb.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            # No exif= argument => the output carries no EXIF metadata.
            rgb.save(buffer, format="JPEG", quality=JPEG_QUALITY)
            return buffer.getvalue()
    except (OSError, ValueError) as exc:
        raise ImageProcessingError(f"could not process image: {exc}") from exc


def fetch_preview(url: str, http_client: httpx.Client) -> bytes:
    """Download an image and return its processed preview bytes.

    Args:
        url: The image URL to fetch.
        http_client: The HTTP client to use (injected for testability).

    Returns:
        JPEG preview bytes per :func:`process_preview`.

    Raises:
        ImageProcessingError: If the download or processing fails.
    """
    return process_preview(download_image(url, http_client))
