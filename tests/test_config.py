"""Tests for lazy environment configuration."""

from __future__ import annotations

import pytest

from tattoo_feed.config import ACCESS_TOKEN_ENV, USER_ID_ENV, Config, load_config
from tattoo_feed.errors import TattooFeedError


def test_load_config_reads_both_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ACCESS_TOKEN_ENV, "tok")
    monkeypatch.setenv(USER_ID_ENV, "uid")
    assert load_config() == Config(access_token="tok", ig_user_id="uid")


@pytest.mark.parametrize("present", [ACCESS_TOKEN_ENV, USER_ID_ENV, None])
def test_load_config_missing_var_raises(
    monkeypatch: pytest.MonkeyPatch, present: str | None
) -> None:
    monkeypatch.delenv(ACCESS_TOKEN_ENV, raising=False)
    monkeypatch.delenv(USER_ID_ENV, raising=False)
    if present is not None:
        monkeypatch.setenv(present, "value")
    with pytest.raises(TattooFeedError):
        load_config()
