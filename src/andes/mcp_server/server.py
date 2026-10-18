"""MCP server entrypoint (stdio transport).

Exposes the three typed tools from ``andes.mcp_server.tools`` over the MCP Python
SDK. Run with:

    python -m andes.mcp_server.server

The SSE transport is provided by the gateway (see ``apps/api``); both call the
same tool functions, so behavior is identical across transports.
"""

from __future__ import annotations

import asyncio

from andes.mcp_server.tools import (
    check_availability,
    create_reservation,
    quote_package,
)


def _check_availability(package_id: str, start_date: str, end_date: str, travelers: int) -> dict:
    """Return availability and the current rate for a package."""
    return check_availability(package_id, start_date, end_date, travelers)


def _quote_package(
    package_id: str,
    travelers: int,
    start_date: str,
    end_date: str,
    options: dict | None = None,
) -> dict:
    """Produce a structured quote with an explicit expiry."""
    return quote_package(package_id, travelers, start_date, end_date, options)


def _create_reservation(
    quote_id: str,
    traveler_id: str,
    idempotency_key: str,
    payment: dict | None = None,
) -> dict:
    """Create a reservation from an accepted, non-expired quote."""
    return create_reservation(quote_id, traveler_id, idempotency_key, payment)


def build_server():  # pragma: no cover - thin SDK wiring
    from mcp.server.mcpserver import MCPServer  # noqa: PLC0415

    server = MCPServer("andes-travel")
    server.add_tool(_check_availability, name="check_availability")
    server.add_tool(_quote_package, name="quote_package")
    server.add_tool(_create_reservation, name="create_reservation")
    return server


def main() -> None:  # pragma: no cover
    asyncio.run(build_server().run_stdio_async())


if __name__ == "__main__":  # pragma: no cover
    main()
