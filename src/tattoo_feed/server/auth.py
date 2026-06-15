"""OAuth 2.1 resource-server token verification.

Validates JWT bearer tokens against an external identity provider's JWKS.
All network I/O uses an injected :class:`httpx.AsyncClient` so tests can
mock the JWKS endpoint with ``respx`` without a live IdP.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from mcp.server.auth.provider import AccessToken

_ISSUER_ENV = "MCP_AUTH_ISSUER"
_JWKS_URL_ENV = "MCP_AUTH_JWKS_URL"
_AUDIENCE_ENV = "MCP_AUTH_AUDIENCE"
_SCOPES_ENV = "MCP_AUTH_REQUIRED_SCOPES"

_ALLOWED_ALGORITHMS = [
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthConfig:
    """Identity-provider settings for resource-server token validation.

    Attributes:
        issuer: Expected ``iss`` claim — the IdP's issuer URL (exact match).
        jwks_url: JWKS endpoint URL used to fetch signature-verification keys.
        audience: Expected ``aud`` claim — the canonical resource-server URL
            used as the RFC 8707 audience binding (the confused-deputy guard).
        required_scopes: Scopes the access token must carry; enforced by the
            SDK ``RequireAuthMiddleware`` after the verifier succeeds.
    """

    issuer: str
    jwks_url: str
    audience: str
    required_scopes: list[str] = field(default_factory=list)


def load_auth_config() -> AuthConfig | None:
    """Load auth config from the environment; return ``None`` if not configured.

    Allows the server to boot and list tools even when IdP credentials have
    not been set, mirroring the lazy-load principle from :func:`load_config`.

    Returns:
        :class:`AuthConfig` when all three mandatory env vars are present,
        ``None`` otherwise.
    """
    issuer = os.environ.get(_ISSUER_ENV)
    jwks_url = os.environ.get(_JWKS_URL_ENV)
    audience = os.environ.get(_AUDIENCE_ENV)
    if not issuer or not jwks_url or not audience:
        return None
    scopes_raw = os.environ.get(_SCOPES_ENV, "")
    scopes = [s.strip() for s in scopes_raw.split(",") if s.strip()]
    return AuthConfig(
        issuer=issuer,
        jwks_url=jwks_url,
        audience=audience,
        required_scopes=scopes,
    )


class IdpTokenVerifier:
    """JWT verifier for an external OAuth 2.1 identity provider.

    Validates a bearer token by:

    1. Fetching the IdP's JWKS once and caching the keys in memory.
    2. Selecting the signing key by the ``kid`` JWT header claim (falls back
       to the first key when ``kid`` is absent).
    3. Calling :func:`jwt.decode`, which atomically verifies the RSA/EC
       signature, the ``iss`` claim, the ``aud`` claim (RFC 8707 audience
       binding — the confused-deputy guard), and the ``exp`` / ``nbf``
       timestamps.
    4. Returning an :class:`~mcp.server.auth.provider.AccessToken` on
       success, or ``None`` on any validation failure so the SDK middleware
       can emit a ``401``.

    Scope enforcement is handled by the SDK's ``RequireAuthMiddleware``
    after this verifier returns; this class only validates the token shape.

    Args:
        issuer: Expected ``iss`` claim (exact string match).
        jwks_url: JWKS endpoint URL on the IdP.
        audience: Expected ``aud`` claim — the resource server's canonical URI.
        http_client: Async HTTP client for JWKS fetching; inject a client
            whose transport is mocked by ``respx`` in tests.
    """

    def __init__(
        self,
        issuer: str,
        jwks_url: str,
        audience: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Initialise the verifier with IdP coordinates and a shared HTTP client."""
        self._issuer = issuer
        self._jwks_url = jwks_url
        self._audience = audience
        self._http = http_client
        self._cached_keys: list[dict[str, Any]] | None = None

    async def _fetch_keys(self) -> list[dict[str, Any]]:
        """Return JWKS keys, fetching from the IdP on the first call.

        Subsequent calls return the cached list without a network round-trip.

        Returns:
            List of JWK dicts from the JWKS response.

        Raises:
            httpx.HTTPStatusError: If the JWKS endpoint returns a non-2xx status.
            KeyError: If the response JSON lacks a ``"keys"`` field.
        """
        if self._cached_keys is None:
            response = await self._http.get(self._jwks_url)
            response.raise_for_status()
            raw: Any = response.json()
            self._cached_keys = list(raw["keys"])
        return self._cached_keys

    async def verify_token(self, token: str) -> AccessToken | None:
        """Validate a JWT bearer token against the configured IdP.

        Args:
            token: Raw JWT string from the ``Authorization: Bearer`` header.

        Returns:
            :class:`~mcp.server.auth.provider.AccessToken` on success;
            ``None`` on any failure (bad signature, wrong ``iss``/``aud``,
            expired, JWKS unreachable, or malformed token).  The SDK
            middleware converts ``None`` into a ``401`` response.
        """
        try:
            keys = await self._fetch_keys()
            header = jwt.get_unverified_header(token)
            kid: Any = header.get("kid")

            signing_key: jwt.PyJWK | None = None
            for key_dict in keys:
                if kid is None or key_dict.get("kid") == kid:
                    signing_key = jwt.PyJWK(key_dict)
                    break

            if signing_key is None:
                log.warning("JWKS: no key matched kid=%s", kid)
                return None

            payload: dict[str, Any] = jwt.decode(
                token,
                signing_key,
                algorithms=_ALLOWED_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud"]},
            )

            client_id = str(payload.get("client_id") or payload.get("sub") or "unknown")
            scope_raw = payload.get("scope", "")
            scopes = [s for s in str(scope_raw).split() if s]

            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=int(payload["exp"]),
                resource=self._audience,
                subject=payload.get("sub"),
                claims=payload,
            )

        except jwt.PyJWTError as exc:
            log.debug("Token rejected: %s", exc)
            return None
        except Exception as exc:
            log.warning("Unexpected error verifying token: %s", exc)
            return None
