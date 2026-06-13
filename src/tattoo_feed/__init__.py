"""Tattoo Feed: an MCP server for curating Instagram tattoo-artist posts.

The package is split into a pure ``core`` (models, errors, repositories, the
Graph client, imaging, and services) and a thin ``server`` adapter that exposes
the core as MCP tools. See ``PLAN.md`` for the full architecture.
"""

__version__ = "0.1.0"
