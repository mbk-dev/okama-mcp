"""Tool registration hub for okama-mcp.

`register_all(mcp)` wires every Phase's tool module into the FastMCP server in a
single call. Each tool module exposes its own `register(mcp)` function.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_all(mcp: FastMCP) -> None:
    """Import every tool module and register its tools with ``mcp``."""
    from okama_mcp.tools import (
        asset,
        asset_list,
        frontier,
        macro,
        monte_carlo,
        plots,
        portfolio,
        search,
    )

    search.register(mcp)
    asset.register(mcp)
    asset_list.register(mcp)
    portfolio.register(mcp)
    monte_carlo.register(mcp)
    frontier.register(mcp)
    macro.register(mcp)
    plots.register(mcp)
