"""Boot test: start the server over stdio with dummy env, list its tools.

This proves the server actually boots with no network and no real credentials,
and that it exposes exactly the tool surface defined in PLAN.md §6.
"""

from __future__ import annotations

import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "list_artists",
    "add_artist",
    "remove_artist",
    "get_feed",
    "next_inspiration",
    "save_to_inspiration",
    "list_inspiration",
    "remove_from_inspiration",
    "reset_seen",
    "record_preference",
    "get_preference_summary",
}


async def test_server_boots_over_stdio_and_lists_expected_tools() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tattoo_feed.server.app"],
        # Dummy (not real) credentials: enough to boot, never used to list tools.
        env={**os.environ, "IG_ACCESS_TOKEN": "dummy-token", "IG_USER_ID": "dummy-id"},
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()

    names = {tool.name for tool in result.tools}
    assert names == EXPECTED_TOOLS
