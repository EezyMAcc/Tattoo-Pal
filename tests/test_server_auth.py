"""Hermetic tests for OAuth 2.1 resource-server token verification (Chunk 2).

A fresh RSA keypair is generated per test session; JWKS fetching is mocked
with ``respx``; no live IdP or network calls are made.  HTTP 401/403 behaviour
is verified via Starlette's ``TestClient`` against the real
:func:`~tattoo_feed.server.app.build_server` factory wired with a test
:class:`AuthConfig` — production construction, not a test-only stub.
"""

from __future__ import annotations

import json
import time
import warnings
from typing import Any

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from jwt.algorithms import RSAAlgorithm
from starlette.testclient import TestClient

from tattoo_feed.server.app import build_server
from tattoo_feed.server.auth import (
    _AUDIENCE_ENV,
    _ISSUER_ENV,
    _JWKS_URL_ENV,
    _SCOPES_ENV,
    AuthConfig,
    IdpTokenVerifier,
    load_auth_config,
)

# ---------------------------------------------------------------------------
# Constants used across all tests
# ---------------------------------------------------------------------------

_ISSUER = "https://idp.example.com/"
_AUDIENCE = "https://mcp.example.com/"
_JWKS_URL = "https://idp.example.com/.well-known/jwks.json"
_SCOPE = "mcp:read"
_KID = "test-key-1"


# ---------------------------------------------------------------------------
# Session-scoped RSA keypair (generated once; shared across all tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rsa_private_key() -> RSAPrivateKey:
    """Generate an RSA-2048 private key for signing test JWTs."""
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )


@pytest.fixture(scope="session")
def jwks_body(rsa_private_key: RSAPrivateKey) -> dict[str, Any]:
    """Build a JWKS dict containing the test public key."""
    pub = rsa_private_key.public_key()
    jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(pub))
    jwk["kid"] = _KID
    return {"keys": [jwk]}


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _make_token(
    private_key: RSAPrivateKey,
    *,
    iss: str = _ISSUER,
    aud: str = _AUDIENCE,
    scope: str = _SCOPE,
    exp_offset: int = 3600,
    include_kid: bool = True,
) -> str:
    """Sign a JWT with the test key.

    Args:
        private_key: RSA private key used for signing.
        iss: ``iss`` claim value.
        aud: ``aud`` claim value.
        scope: Space-separated scope string placed in the ``scope`` claim.
        exp_offset: Seconds added to ``time.time()`` for the ``exp`` claim.
            Pass a negative value to create an expired token.
        include_kid: Whether to add the ``kid`` header.
    """
    payload = {
        "iss": iss,
        "aud": aud,
        "sub": "test-user",
        "client_id": "test-client",
        "scope": scope,
        "exp": int(time.time()) + exp_offset,
    }
    headers: dict[str, str] = {"kid": _KID} if include_kid else {}
    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)


def _test_auth_cfg() -> AuthConfig:
    """Return an AuthConfig pointing at the test IdP constants."""
    return AuthConfig(
        issuer=_ISSUER,
        jwks_url=_JWKS_URL,
        audience=_AUDIENCE,
        required_scopes=[_SCOPE],
    )


# ---------------------------------------------------------------------------
# load_auth_config tests
# ---------------------------------------------------------------------------


def test_load_auth_config_returns_none_when_all_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_auth_config returns None when no env vars are set."""
    for env in (_ISSUER_ENV, _JWKS_URL_ENV, _AUDIENCE_ENV, _SCOPES_ENV):
        monkeypatch.delenv(env, raising=False)
    assert load_auth_config() is None


def test_load_auth_config_returns_none_when_jwks_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_auth_config returns None when JWKS URL is missing."""
    monkeypatch.setenv(_ISSUER_ENV, _ISSUER)
    monkeypatch.delenv(_JWKS_URL_ENV, raising=False)
    monkeypatch.setenv(_AUDIENCE_ENV, _AUDIENCE)
    assert load_auth_config() is None


def test_load_auth_config_returns_none_when_audience_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_auth_config returns None when audience is missing."""
    monkeypatch.setenv(_ISSUER_ENV, _ISSUER)
    monkeypatch.setenv(_JWKS_URL_ENV, _JWKS_URL)
    monkeypatch.delenv(_AUDIENCE_ENV, raising=False)
    assert load_auth_config() is None


def test_load_auth_config_returns_config_with_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_auth_config returns AuthConfig with parsed scopes."""
    monkeypatch.setenv(_ISSUER_ENV, _ISSUER)
    monkeypatch.setenv(_JWKS_URL_ENV, _JWKS_URL)
    monkeypatch.setenv(_AUDIENCE_ENV, _AUDIENCE)
    monkeypatch.setenv(_SCOPES_ENV, "mcp:read, mcp:write")
    cfg = load_auth_config()
    assert cfg is not None
    assert cfg == AuthConfig(
        issuer=_ISSUER,
        jwks_url=_JWKS_URL,
        audience=_AUDIENCE,
        required_scopes=["mcp:read", "mcp:write"],
    )


def test_load_auth_config_returns_config_without_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_auth_config returns AuthConfig with empty scopes when unset."""
    monkeypatch.setenv(_ISSUER_ENV, _ISSUER)
    monkeypatch.setenv(_JWKS_URL_ENV, _JWKS_URL)
    monkeypatch.setenv(_AUDIENCE_ENV, _AUDIENCE)
    monkeypatch.delenv(_SCOPES_ENV, raising=False)
    cfg = load_auth_config()
    assert cfg is not None
    assert cfg.required_scopes == []


# ---------------------------------------------------------------------------
# IdpTokenVerifier.verify_token — unit tests (async, no HTTP server)
# ---------------------------------------------------------------------------


@respx.mock
async def test_verify_token_valid_returns_access_token(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A correctly signed token with matching claims yields an AccessToken."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    token = _make_token(rsa_private_key)

    async with httpx.AsyncClient() as client:
        verifier = IdpTokenVerifier(_ISSUER, _JWKS_URL, _AUDIENCE, client)
        result = await verifier.verify_token(token)

    assert result is not None
    assert _SCOPE in result.scopes
    assert result.client_id == "test-client"
    assert result.resource == _AUDIENCE
    assert result.subject == "test-user"


@respx.mock
async def test_verify_token_caches_jwks(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """The JWKS endpoint is fetched only once; subsequent calls use the cache."""
    route = respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    token = _make_token(rsa_private_key)

    async with httpx.AsyncClient() as client:
        verifier = IdpTokenVerifier(_ISSUER, _JWKS_URL, _AUDIENCE, client)
        await verifier.verify_token(token)  # populates cache
        await verifier.verify_token(token)  # uses cache

    assert route.call_count == 1, "JWKS should be fetched exactly once"


@respx.mock
async def test_verify_token_wrong_audience_returns_none(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A token with the wrong aud claim is rejected (RFC 8707 audience binding)."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    token = _make_token(rsa_private_key, aud="https://other.example.com/")

    async with httpx.AsyncClient() as client:
        verifier = IdpTokenVerifier(_ISSUER, _JWKS_URL, _AUDIENCE, client)
        result = await verifier.verify_token(token)

    assert result is None


@respx.mock
async def test_verify_token_wrong_issuer_returns_none(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A token with the wrong iss claim is rejected."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    token = _make_token(rsa_private_key, iss="https://evil.example.com/")

    async with httpx.AsyncClient() as client:
        verifier = IdpTokenVerifier(_ISSUER, _JWKS_URL, _AUDIENCE, client)
        result = await verifier.verify_token(token)

    assert result is None


@respx.mock
async def test_verify_token_expired_returns_none(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """An expired token (exp in the past) is rejected."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    token = _make_token(rsa_private_key, exp_offset=-3600)

    async with httpx.AsyncClient() as client:
        verifier = IdpTokenVerifier(_ISSUER, _JWKS_URL, _AUDIENCE, client)
        result = await verifier.verify_token(token)

    assert result is None


@respx.mock
async def test_verify_token_no_matching_kid_returns_none(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A token whose kid header matches no JWKS key is rejected."""
    # Use a different kid so no key matches
    bad_token = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "u1",
            "scope": _SCOPE,
            "exp": int(time.time()) + 3600,
        },
        rsa_private_key,
        algorithm="RS256",
        headers={"kid": "nonexistent-key"},
    )
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))

    async with httpx.AsyncClient() as client:
        verifier = IdpTokenVerifier(_ISSUER, _JWKS_URL, _AUDIENCE, client)
        result = await verifier.verify_token(bad_token)

    assert result is None


@respx.mock
async def test_verify_token_no_kid_header_uses_first_key(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A token without a kid header falls back to the first JWKS key."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    token = _make_token(rsa_private_key, include_kid=False)

    async with httpx.AsyncClient() as client:
        verifier = IdpTokenVerifier(_ISSUER, _JWKS_URL, _AUDIENCE, client)
        result = await verifier.verify_token(token)

    # The first (only) key in our JWKS matches → should verify successfully
    assert result is not None


@respx.mock
async def test_verify_token_malformed_jwks_returns_none(
    rsa_private_key: RSAPrivateKey,
) -> None:
    """A JWKS response without the 'keys' field triggers the generic handler."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json={"not_keys": []}))
    token = _make_token(rsa_private_key)

    async with httpx.AsyncClient() as client:
        verifier = IdpTokenVerifier(_ISSUER, _JWKS_URL, _AUDIENCE, client)
        result = await verifier.verify_token(token)

    assert result is None


# ---------------------------------------------------------------------------
# HTTP endpoint integration tests — drive the real build_server factory
# ---------------------------------------------------------------------------


@respx.mock
def test_unauthenticated_request_gets_401(
    jwks_body: dict[str, Any],
) -> None:
    """A request with no Authorization header receives a 401 with resource_metadata."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    starlette_app = build_server(_test_auth_cfg()).streamable_http_app()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with TestClient(starlette_app, raise_server_exceptions=False) as client:
            response = client.get("/mcp")

    assert response.status_code == 401
    www_auth = response.headers.get("www-authenticate", "")
    assert "Bearer" in www_auth
    assert "resource_metadata=" in www_auth


@respx.mock
def test_valid_token_is_accepted(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A valid bearer token passes auth *and* the DNS-rebinding host check.

    The request is driven from the allow-listed audience host
    (``mcp.example.com``), not the ``TestClient`` default ``testserver`` — with
    the default host the transport-security guard (correctly) returns ``421``
    before the MCP layer is reached. ``421`` is asserted *out* so a host-check
    regression can no longer hide behind a non-auth status.
    """
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    starlette_app = build_server(_test_auth_cfg()).streamable_http_app()
    token = _make_token(rsa_private_key)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with TestClient(
            starlette_app,
            base_url="https://mcp.example.com",
            raise_server_exceptions=False,
        ) as client:
            response = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    # Past auth AND past the host check: the MCP endpoint may return any other
    # non-auth status, but never 401/403 (auth) or 421 (rejected host).
    assert response.status_code not in (401, 403, 421)


@respx.mock
def test_wrong_scope_gets_403(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A valid token that lacks the required scope receives 403 insufficient_scope."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    starlette_app = build_server(_test_auth_cfg()).streamable_http_app()
    token = _make_token(rsa_private_key, scope="wrong:scope")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with TestClient(starlette_app, raise_server_exceptions=False) as client:
            response = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    body = response.json()
    assert body.get("error") == "insufficient_scope"


@respx.mock
def test_wrong_audience_token_gets_401(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A token with a wrong aud claim is rejected with 401 at the HTTP layer."""
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    starlette_app = build_server(_test_auth_cfg()).streamable_http_app()
    token = _make_token(rsa_private_key, aud="https://other.example.com/")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with TestClient(starlette_app, raise_server_exceptions=False) as client:
            response = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Protected-resource metadata endpoint
# ---------------------------------------------------------------------------


def test_protected_resource_metadata_is_served() -> None:
    """The /.well-known/oauth-protected-resource endpoint returns valid metadata."""
    starlette_app = build_server(_test_auth_cfg()).streamable_http_app()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with TestClient(starlette_app, raise_server_exceptions=False) as client:
            response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    body = response.json()
    # Resource URL and the authorization server must be present
    assert body["resource"] == _AUDIENCE
    assert _ISSUER in body["authorization_servers"]
    assert _SCOPE in body.get("scopes_supported", [])


# ---------------------------------------------------------------------------
# DNS-rebinding host allow-list (Bug 2 — the 421-under-ngrok regression guard)
# ---------------------------------------------------------------------------


def test_build_server_allowlists_audience_host() -> None:
    """An auth-configured server adds the audience host to allowed_hosts.

    FastMCP freezes its DNS-rebinding allow-list from the constructor host
    (localhost) at construction time; behind a tunnel that yields a 421 on every
    authenticated request. build_server must re-point the guard at the public
    host derived from the audience. This settings-level assertion catches that
    regression in the gate, without a live tunnel.
    """
    server = build_server(_test_auth_cfg())  # audience = https://mcp.example.com/
    allowed = server.settings.transport_security.allowed_hosts
    assert "mcp.example.com" in allowed


def test_build_server_no_auth_keeps_localhost_lock() -> None:
    """Without auth, the server keeps the localhost-locked default (stdio posture).

    The host list is widened only for the authenticated HTTP build; the
    local/stdio build must stay locked to localhost and never carry a public
    host.
    """
    server = build_server(None)
    allowed = server.settings.transport_security.allowed_hosts
    assert "127.0.0.1:*" in allowed
    assert all("mcp.example.com" not in h for h in allowed)


@respx.mock
def test_disallowed_host_still_rejected(
    rsa_private_key: RSAPrivateKey,
    jwks_body: dict[str, Any],
) -> None:
    """A valid token from a non-allow-listed Host is still refused with 421.

    Counterpart to test_valid_token_is_accepted: that proves the right host gets
    through; this proves a wrong host is still blocked — i.e. the guard is
    narrowed to our host, not disabled.
    """
    respx.get(_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body))
    starlette_app = build_server(_test_auth_cfg()).streamable_http_app()
    token = _make_token(rsa_private_key)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with TestClient(
            starlette_app,
            base_url="https://evil.example",
            raise_server_exceptions=False,
        ) as client:
            response = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 421
