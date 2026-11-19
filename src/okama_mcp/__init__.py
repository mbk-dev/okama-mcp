"""okama-mcp: an MCP server wrapping the okama investment toolkit.

Exposes a FastMCP server through both stdio and streamable-http transports so AI
assistants can run portfolio backtests, Monte Carlo forecasts, efficient-frontier
optimisation and macro queries via tool calls.
"""

from __future__ import annotations

from importlib.metadata import version

__version__ = version("okama-mcp")
