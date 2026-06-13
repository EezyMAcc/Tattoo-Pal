"""Tests for the typed error hierarchy."""

import pytest

from tattoo_feed.errors import (
    AccountNotFoundError,
    ImageProcessingError,
    NotAProfessionalAccountError,
    RateLimitedError,
    RepositoryError,
    TattooFeedError,
    TokenExpiredError,
)


@pytest.mark.parametrize(
    "error_cls",
    [
        TokenExpiredError,
        AccountNotFoundError,
        NotAProfessionalAccountError,
        RateLimitedError,
        RepositoryError,
        ImageProcessingError,
    ],
)
def test_all_errors_subclass_base(error_cls: type[TattooFeedError]) -> None:
    err = error_cls("boom")
    assert isinstance(err, TattooFeedError)
    assert isinstance(err, Exception)
    assert str(err) == "boom"


def test_rate_limited_carries_retry_after() -> None:
    err = RateLimitedError("slow down", retry_after_seconds=12.5)
    assert err.retry_after_seconds == 12.5
    assert str(err) == "slow down"


def test_rate_limited_retry_after_defaults_to_none() -> None:
    err = RateLimitedError("slow down")
    assert err.retry_after_seconds is None


def test_base_error_can_be_raised_and_caught() -> None:
    with pytest.raises(TattooFeedError):
        raise TokenExpiredError("expired")
