"""Typed error hierarchy for the tattoo_feed core.

Every failure that crosses a module boundary is one of these. Nothing in
``core`` raises a bare :class:`Exception`; callers can therefore branch on
intent (token expired vs. account missing vs. rate limited) rather than on
string-matching, and the ``server`` layer can map each to a clean client
message.
"""


class TattooFeedError(Exception):
    """Base class for every error raised by the tattoo_feed core."""


class TokenExpiredError(TattooFeedError):
    """The Instagram access token has expired or been revoked.

    There is deliberately no automatic refresh (see ``PLAN.md`` §2); the user
    must mint a new long-lived token and update the environment.
    """


class AccountNotFoundError(TattooFeedError):
    """No Instagram account could be resolved for the requested handle."""


class NotAProfessionalAccountError(TattooFeedError):
    """The handle resolved, but it is not a Business/Creator account.

    Business Discovery only works against professional accounts, so a personal
    account cannot be tracked.
    """


class RateLimitedError(TattooFeedError):
    """Instagram returned an HTTP 429 (rate limit) for the request."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        """Store the message and an optional server-suggested retry delay.

        Args:
            message: Human-readable description of the rate-limit condition.
            retry_after_seconds: Seconds to wait before retrying, if the API
                provided a hint; ``None`` when unknown.
        """
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class RepositoryError(TattooFeedError):
    """A persistence operation failed (read, write, or corrupt store)."""


class ImageProcessingError(TattooFeedError):
    """Downloading or downscaling a preview image failed."""
