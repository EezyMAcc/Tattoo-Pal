"""Tests for the Pydantic domain models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tattoo_feed.models import (
    Artist,
    InspirationItem,
    MediaType,
    Post,
    Preference,
)

TS = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


def _post(**overrides: object) -> Post:
    data: dict[str, object] = {
        "id": "media-1",
        "artist_handle": "artist",
        "caption": "ink",
        "media_type": MediaType.IMAGE,
        "image_url": "https://example.com/a.jpg",
        "permalink": "https://instagram.com/p/abc",
        "timestamp": TS,
    }
    data.update(overrides)
    return Post(**data)  # type: ignore[arg-type]  # test helper builds valid kwargs


def test_post_round_trips_through_dump_and_validate() -> None:
    post = _post()
    restored = Post.model_validate(post.model_dump())
    assert restored == post


def test_post_rejects_video_media_type() -> None:
    with pytest.raises(ValidationError):
        _post(media_type="VIDEO")


def test_post_caption_optional() -> None:
    assert _post(caption=None).caption is None


def test_post_requires_non_empty_id() -> None:
    with pytest.raises(ValidationError):
        _post(id="")


@pytest.mark.parametrize("raw", ["@Artist", "  artist  ", "ARTIST"])
def test_handle_normalization(raw: str) -> None:
    assert (
        Post(
            id="m",
            artist_handle=raw,
            media_type=MediaType.IMAGE,
            image_url="https://example.com/a.jpg",
            permalink="https://instagram.com/p/abc",
            timestamp=TS,
        ).artist_handle
        == "artist"
    )


def test_artist_defaults_added_at_to_utc() -> None:
    artist = Artist(handle="@SomeArtist")
    assert artist.handle == "someartist"
    assert artist.ig_user_id is None
    assert artist.added_at.tzinfo is not None


def test_artist_rejects_blank_handle() -> None:
    with pytest.raises(ValidationError):
        Artist(handle="@")


def test_inspiration_item_round_trips_and_normalizes_handle() -> None:
    item = InspirationItem(
        post_id="m1",
        artist_handle="@Artist",
        image_url="https://example.com/a.jpg",
        permalink="https://instagram.com/p/abc",
        timestamp=TS,
        notes="love the linework",
    )
    assert item.artist_handle == "artist"
    assert InspirationItem.model_validate(item.model_dump()) == item


def test_inspiration_notes_optional_and_save_order_timestamp_set() -> None:
    item = InspirationItem(
        post_id="m1",
        artist_handle="artist",
        image_url="https://example.com/a.jpg",
        permalink="https://instagram.com/p/abc",
        timestamp=TS,
    )
    assert item.notes is None
    assert item.saved_at.tzinfo is not None


def test_preference_generates_id_and_strips_observation() -> None:
    pref = Preference(observation="  bold blackwork  ")
    assert pref.observation == "bold blackwork"
    assert pref.id
    assert pref.created_at.tzinfo is not None


def test_preference_ids_are_unique() -> None:
    assert Preference(observation="a").id != Preference(observation="b").id


def test_preference_rejects_blank_observation() -> None:
    with pytest.raises(ValidationError):
        Preference(observation="   ")


def test_models_are_frozen() -> None:
    post = _post()
    with pytest.raises(ValidationError):
        post.caption = "changed"  # type: ignore[misc]  # asserting immutability
