"""Single-asset tools: ``get_asset_history``.

For a given ticker, return one of okama's time-series properties — monthly close,
daily close, dividend-adjusted close, monthly rate of return, or dividends. The
choice is exposed as a ``kind`` parameter so the LLM can pick what it needs
without us having to ship four separate tools.
"""

from __future__ import annotations

from typing import Any

import okama as ok
from fastmcp import FastMCP

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.serialization import series_to_json, value_to_json

_VALID_KINDS = ("close_monthly", "close_daily", "adj_close", "ror", "dividends")


@translates_okama_errors
def get_asset_history(
    symbol: str,
    first_date: str | None = None,
    last_date: str | None = None,
    kind: str = "close_monthly",
    full: bool = False,
) -> dict[str, Any]:
    """Return a historical time series for a single asset.

    Parameters
    ----------
    symbol : str
        okama ticker, e.g. 'GLD.US', 'VNQ.US', 'AAPL.US'.
    first_date, last_date : str, optional
        ISO 'YYYY-MM' bounds (inclusive).
    kind : {'close_monthly', 'close_daily', 'adj_close', 'ror', 'dividends'}
        Which time series to return. Default is monthly close price.
    full : bool, default False
        If True, return the entire series. Otherwise long series (>500 rows) are
        truncated to head/tail/summary to keep response size manageable.

    Returns
    -------
    dict with the symbol, currency, kind, date range, and the serialised series.
    """
    if kind not in _VALID_KINDS:
        raise OkamaMcpError(f"kind must be one of {_VALID_KINDS}, got {kind!r}")

    asset = ok.Asset(symbol, first_date=first_date, last_date=last_date)
    series = getattr(asset, kind)

    return {
        "symbol": getattr(asset, "symbol", symbol),
        "currency": getattr(asset, "currency", None),
        "kind": kind,
        "first_date": value_to_json(getattr(asset, "first_date", None)),
        "last_date": value_to_json(getattr(asset, "last_date", None)),
        "series": series_to_json(series, full=full),
    }


def register(mcp: FastMCP) -> None:
    """Register single-asset tools with the FastMCP server."""
    mcp.tool(get_asset_history)
