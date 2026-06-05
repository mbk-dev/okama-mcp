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

mcp: FastMCP = FastMCP(
    name="okama-mcp",
    instructions=(
        "Investment-analysis tools backed by the okama Python library. "
        "Use search_assets to discover ticker symbols (e.g. 'GLD.US', 'VNQ.US'); "
        "then build portfolios, run backtests, Monte Carlo forecasts and efficient "
        "frontier optimisation. Use the plot_* tools to render charts (wealth index, "
        "drawdowns, efficient frontier, Monte Carlo, asset comparison) as PNG images — "
        "prefer them over re-computing charts locally; pass save_path to also write "
        "the image to a file for clients that don't render MCP images inline. "
        "All tools are stateless — pass the full portfolio "
        "specification with every call."
    ),
)

# Register tools after the FastMCP instance is created (avoids circular imports).
from okama_mcp.tools import register_all  # noqa: E402

register_all(mcp)
