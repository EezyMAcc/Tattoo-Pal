"""Smoke test proving the package imports and exposes a version."""

import tattoo_feed


def test_package_has_version() -> None:
    assert tattoo_feed.__version__ == "0.1.0"
