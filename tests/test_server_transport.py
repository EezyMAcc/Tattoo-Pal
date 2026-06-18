"""Tests for the transport-selection helper in server.app.

All tests are hermetic: no server is booted, no network calls are made.
The helper is a pure function over environment variables.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from tattoo_feed.server.app import (
    TransportConfig,
    resolve_transport,
    run_server,
)


def test_transport_default_is_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    """When MCP_TRANSPORT is unset, resolve_transport picks stdio."""
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    config = resolve_transport()
    assert config.transport == "stdio"


def test_transport_http_selects_streamable_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP_TRANSPORT=http picks streamable-http with custom host and port."""
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_PORT", "9000")
    config = resolve_transport()
    assert config.transport == "streamable-http"
    assert config.host == "127.0.0.1"
    assert config.port == 9000


def test_transport_http_uses_defaults_when_env_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP_TRANSPORT=http with no host/port env vars falls back to 0.0.0.0:8000."""
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.delenv("MCP_PORT", raising=False)
    config = resolve_transport()
    assert config.transport == "streamable-http"
    assert config.host == "0.0.0.0"
    assert config.port == 8000


# ---------------------------------------------------------------------------
# run_server — dispatch logic, with FastMCP.run patched to a no-op so the
# host/port binding and the HTTP-vs-stdio branch are covered without booting.
# ---------------------------------------------------------------------------


def _patch_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch FastMCP.run to record its server + kwargs instead of blocking."""
    captured: dict[str, Any] = {}

    def fake_run(self: FastMCP, *args: Any, **kwargs: Any) -> None:
        captured["server"] = self
        captured["kwargs"] = kwargs

    monkeypatch.setattr(FastMCP, "run", fake_run)
    return captured


def test_run_server_http_binds_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The streamable-http path binds the configured host/port and runs HTTP."""
    # No auth env → build_server(None); keeps the test hermetic (no AsyncClient).
    for var in ("MCP_AUTH_ISSUER", "MCP_AUTH_JWKS_URL", "MCP_AUTH_AUDIENCE"):
        monkeypatch.delenv(var, raising=False)
    captured = _patch_run(monkeypatch)

    run_server(TransportConfig(transport="streamable-http", host="1.2.3.4", port=9999))

    assert captured["kwargs"].get("transport") == "streamable-http"
    assert captured["server"].settings.host == "1.2.3.4"
    assert captured["server"].settings.port == 9999


def test_run_server_stdio_runs_with_default_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stdio path runs with no explicit transport (SDK default = stdio)."""
    captured = _patch_run(monkeypatch)

    run_server(TransportConfig(transport="stdio", host="0.0.0.0", port=8000))

    # stdio branch calls build_server(None).run() — no transport kwarg.
    assert captured["kwargs"].get("transport") is None
    assert "server" in captured
