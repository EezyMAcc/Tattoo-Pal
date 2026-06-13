"""Pydantic v2 domain models.

These are the value objects that cross every boundary in the system: what the
Graph client returns, what the repositories persist, and what the services
hand back to the MCP layer. They are frozen (immutable) so they behave as
plain values — safe to share, compare, and hash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MediaType(StrEnum):
    """The kinds of post that may enter the system.

    Videos are filtered out at the Graph-client layer and so never become a
    :class:`Post`; only still images and carousel albums (rendered as their
    first image) are represented here.
    """

    IMAGE = "IMAGE"
    CAROUSEL_ALBUM = "CAROUSEL_ALBUM"


def _normalize_handle(value: str) -> str:
    """Normalize an Instagram handle to its canonical bare form.

    Users naturally type ``@artist``; Instagram identifies the account as
    ``artist``. Stripping the leading ``@`` and surrounding whitespace and
    lower-casing keeps stored handles consistent and de-duplicated.

    Args:
        value: The raw handle as entered.

    Returns:
        The trimmed, ``@``-free, lower-cased handle.
    """
    return value.strip().removeprefix("@").lower()


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Post(BaseModel):
    """A single image post fetched from an artist's feed.

    Attributes:
        id: Instagram's media id.
        artist_handle: The bare handle of the artist who posted it.
        caption: The post caption, or ``None`` if there is none.
        media_type: ``IMAGE`` or ``CAROUSEL_ALBUM`` (never video).
        image_url: URL of the (first) image to preview.
        permalink: Public Instagram URL of the post, used for attribution.
        timestamp: When the post was published.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    artist_handle: str
    caption: str | None = None
    media_type: MediaType
    image_url: str = Field(min_length=1)
    permalink: str = Field(min_length=1)
    timestamp: datetime

    @field_validator("artist_handle")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return _normalize_handle(value)


class Artist(BaseModel):
    """A tracked tattoo artist.

    Attributes:
        handle: The bare Instagram handle (without ``@``).
        ig_user_id: The resolved Business Discovery user id, if known.
        added_at: When the artist was added to the tracked list.
    """

    model_config = ConfigDict(frozen=True)

    handle: str = Field(min_length=1)
    ig_user_id: str | None = None
    added_at: datetime = Field(default_factory=_utc_now)

    @field_validator("handle")
    @classmethod
    def _normalize(cls, value: str) -> str:
        normalized = _normalize_handle(value)
        if not normalized:
            raise ValueError("handle must not be empty")
        return normalized


class InspirationItem(BaseModel):
    """A post the user has saved into their inspiration collection.

    The artist handle is stored explicitly (not just the post id) so a future
    GUI can render an attribution bubble without re-fetching the post.

    Attributes:
        post_id: Instagram media id of the saved post.
        artist_handle: Bare handle of the artist, for attribution.
        image_url: URL of the saved image.
        permalink: Public Instagram URL of the post.
        timestamp: When the post was originally published.
        notes: Optional free-text note the user attached.
        saved_at: When the item was saved (defines save order).
    """

    model_config = ConfigDict(frozen=True)

    post_id: str = Field(min_length=1)
    artist_handle: str
    image_url: str = Field(min_length=1)
    permalink: str = Field(min_length=1)
    timestamp: datetime
    notes: str | None = None
    saved_at: datetime = Field(default_factory=_utc_now)

    @field_validator("artist_handle")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return _normalize_handle(value)


class Preference(BaseModel):
    """A captured note about the user's taste (distinct from a saved image).

    Attributes:
        id: Stable identifier for the preference.
        observation: The taste observation in natural language.
        created_at: When the preference was recorded.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    observation: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("observation")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("observation must not be blank")
        return stripped
