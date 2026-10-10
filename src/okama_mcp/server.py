"""FastMCP server instance for okama-mcp.

Tools are registered by importing modules from `okama_mcp.tools`. Phase 0 ships an
empty registry; subsequent phases add search, asset, portfolio, Monte Carlo,
frontier and macro tools.
"""

from __future__ import annotations

import os

# Force matplotlib's headless backend before importing okama. okama imports
# matplotlib eagerly, and on a headless server (HTTP transport on secondvds)
# the default backend can raise at import time.
os.environ.setdefault("MPLBACKEND", "Agg")

from fastmcp import FastMCP  # noqa: E402

def create_server(language: str = "en") -> FastMCP:
    """Construct an isolated public registry before attaching optional local tools."""
    from okama_mcp.tools import register_all

    server = FastMCP(
        name="okama-mcp",
        mask_error_details=True,
        instructions=(
            "Investment-analysis tools backed by the okama Python library. "
            "Use search_assets to discover ticker symbols, filter asset types, or find the "
            "oldest history in a namespace (e.g. 'GLD.US', 'VNQ.US'); "
            "then build portfolios, run backtests, Monte Carlo forecasts and efficient "
            "frontier optimisation. Use the plot_* tools to render charts (wealth index, "
            "drawdowns, efficient frontier, Monte Carlo, asset comparison) as PNG images — "
            "prefer them over re-computing charts locally; pass save_path to also write "
            "the image to a file for clients that don't render MCP images inline. "
            "Financial tools are stateless — pass the full portfolio "
            "specification with every call."
        ),
    )

    register_all(server, language=language)
    return server


mcp: FastMCP = create_server()
