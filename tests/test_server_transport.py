"""Tests for the transport-selection helper in server.app.

All tests are hermetic: no server is booted, no network calls are made.
The helper is a pure function over environment variables.
"""

from __future__ import annotations

import pytest

from tattoo_feed.server.app import resolve_transport


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
