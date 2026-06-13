"""Lazy environment configuration.

Credentials are read from the environment on demand — never at import time —
so the MCP server can boot and list its tools with no real credentials and no
network access. Only when a tool actually calls Instagram is the config loaded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from tattoo_feed.errors import TattooFeedError

ACCESS_TOKEN_ENV = "IG_ACCESS_TOKEN"
USER_ID_ENV = "IG_USER_ID"


@dataclass(frozen=True)
class Config:
    """Resolved runtime credentials.

    Attributes:
        access_token: Long-lived Instagram Graph API access token.
        ig_user_id: The querying Business/Creator account id.
    """

    access_token: str
    ig_user_id: str


def load_config() -> Config:
    """Load credentials from the environment.

    Returns:
        The resolved :class:`Config`.

    Raises:
        TattooFeedError: If either environment variable is missing or empty.
    """
    token = os.environ.get(ACCESS_TOKEN_ENV)
    user_id = os.environ.get(USER_ID_ENV)
    if not token or not user_id:
        raise TattooFeedError(
            f"{ACCESS_TOKEN_ENV} and {USER_ID_ENV} must both be set; "
            "copy .env.example to .env and fill in your credentials."
        )
    return Config(access_token=token, ig_user_id=user_id)
