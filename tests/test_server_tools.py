"""In-process tests of the MCP tool wrappers (separate from the stdio boot).

These call the thin tool functions directly with fake services injected, so the
adapter layer is covered without spawning a subprocess.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from tattoo_feed.models import Artist, InspirationItem, MediaType, Post, Preference
from tattoo_feed.server import app

TS = datetime(2024, 3, 4, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "sample.jpg"


def _post(post_id: str = "p1") -> Post:
    return Post(
        id=post_id,
        artist_handle="alice",
        caption="fine line",
        media_type=MediaType.IMAGE,
        image_url=f"https://cdn/{post_id}.jpg",
        permalink=f"https://ig/p/{post_id}",
        timestamp=TS,
    )


class FakeArtists:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def list_artists(self) -> list[Artist]:
        return [Artist(handle="alice")]

    def add_artist(self, handle: str) -> Artist:
        return Artist(handle=handle, ig_user_id="id-1")

    def remove_artist(self, handle: str) -> None:
        self.removed.append(handle)


class FakeFeed:
    def get_feed(self, limit_per_artist: int = 10) -> list[Post]:
        return [_post("p1"), _post("p2")]


class FakeInspiration:
    def __init__(self, post: Post | None) -> None:
        self._post = post
        self.reset_called = False
        self.removed: list[str] = []

    def next_inspiration(self) -> Post | None:
        return self._post

    def save_to_inspiration(
        self, post_id: str, notes: str | None = None
    ) -> InspirationItem:
        return InspirationItem(
            post_id=post_id,
            artist_handle="alice",
            image_url="https://cdn/x.jpg",
            permalink="https://ig/p/x",
            timestamp=TS,
            notes=notes,
        )

    def list_inspiration(self) -> list[InspirationItem]:
        return [
            InspirationItem(
                post_id="p1",
                artist_handle="alice",
                image_url="https://cdn/x.jpg",
                permalink="https://ig/p/x",
                timestamp=TS,
            )
        ]

    def remove_from_inspiration(self, post_id: str) -> None:
        self.removed.append(post_id)

    def reset_seen(self) -> None:
        self.reset_called = True


class FakePrefs:
    def record_preference(self, observation: str) -> Preference:
        return Preference(observation=observation)

    def get_preference_summary(self) -> list[Preference]:
        return [Preference(observation="loves blackwork")]


def _install(post: Post | None) -> app._Services:
    services = app._Services(
        artists=FakeArtists(),  # type: ignore[arg-type]
        feed=FakeFeed(),  # type: ignore[arg-type]
        inspiration=FakeInspiration(post),  # type: ignore[arg-type]
        preferences=FakePrefs(),  # type: ignore[arg-type]
        http=None,  # type: ignore[arg-type]
    )
    app._services = services
    return services


@pytest.fixture(autouse=True)
def _reset_services() -> Iterator[None]:
    app._services = None
    yield
    app._services = None


def test_list_artists() -> None:
    _install(_post())
    assert [a.handle for a in app.list_artists()] == ["alice"]


def test_add_artist() -> None:
    _install(_post())
    assert app.add_artist("@Bob").handle == "bob"


def test_remove_artist_returns_confirmation() -> None:
    services = _install(_post())
    msg = app.remove_artist("alice")
    assert "alice" in msg
    assert services.artists.removed == ["alice"]  # type: ignore[attr-defined]


def test_get_feed() -> None:
    _install(_post())
    assert [p.id for p in app.get_feed()] == ["p1", "p2"]


@respx.mock
def test_next_inspiration_returns_image_then_metadata() -> None:
    services = _install(_post("p9"))
    services.http = httpx.Client()
    respx.get("https://cdn/p9.jpg").mock(
        return_value=httpx.Response(200, content=FIXTURE.read_bytes())
    )
    blocks = app.next_inspiration()
    assert blocks[0].type == "image"
    assert blocks[0].mimeType == "image/jpeg"
    assert blocks[1].type == "text"
    assert "@alice" in blocks[1].text
    assert "https://ig/p/p9" in blocks[1].text


def test_next_inspiration_when_nothing_new() -> None:
    _install(None)
    blocks = app.next_inspiration()
    assert blocks[0].type == "text"
    assert "reset_seen" in blocks[0].text


def test_save_to_inspiration_passes_notes() -> None:
    _install(_post())
    item = app.save_to_inspiration("p1", notes="love it")
    assert item.post_id == "p1"
    assert item.notes == "love it"


def test_list_inspiration() -> None:
    _install(_post())
    assert [i.post_id for i in app.list_inspiration()] == ["p1"]


def test_remove_from_inspiration_returns_confirmation() -> None:
    services = _install(_post())
    msg = app.remove_from_inspiration("p1")
    assert "p1" in msg
    assert services.inspiration.removed == ["p1"]  # type: ignore[attr-defined]


def test_reset_seen_returns_confirmation() -> None:
    services = _install(_post())
    msg = app.reset_seen()
    assert "cleared" in msg.lower()
    assert services.inspiration.reset_called is True  # type: ignore[attr-defined]


def test_record_preference() -> None:
    _install(_post())
    assert app.record_preference("loves blackwork").observation == "loves blackwork"


def test_get_preference_summary() -> None:
    _install(_post())
    assert [p.observation for p in app.get_preference_summary()] == ["loves blackwork"]


def test_build_services_is_lazy_and_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "uid")
    monkeypatch.setenv(app.DATA_DIR_ENV, str(tmp_path))
    app._services = None

    first = app._get_services()
    second = app._get_services()
    assert first is second  # cached singleton
    assert [a.handle for a in first.artists.list_artists()] == []  # no network
    first.http.close()
