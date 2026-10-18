from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")

from andes.mcp_server.server import build_server  # noqa: E402

EXPECTED = {"check_availability", "quote_package", "create_reservation"}


def test_server_lists_all_tools():
    server = build_server()
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == EXPECTED


def test_server_call_quote():
    server = build_server()
    result = asyncio.run(
        server.call_tool(
            "quote_package",
            {
                "package_id": "11111111-1111-1111-1111-111111111101",
                "travelers": 2,
                "start_date": "2026-03-01",
                "end_date": "2026-03-06",
            },
        )
    )
    assert result
