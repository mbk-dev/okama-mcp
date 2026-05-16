"""Multi-asset comparison tools: ``compare_assets``, ``get_correlations``.

okama.AssetList is the right primitive when the user wants to *compare* two or
more assets without committing to a portfolio (weights). ``describe()`` gives a
full statistical summary across 1/5/10-year windows and since-inception; the
correlation matrix is a separate tool because users often want only that.
"""

from __future__ import annotations

from typing import Any

import okama as ok
from fastmcp import FastMCP

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.serialization import dataframe_to_json, value_to_json


def _build_asset_list(
    symbols: list[str],
    ccy: str,
    first_date: str | None,
    last_date: str | None,
    inflation: bool,
) -> Any:
    if not symbols:
        raise OkamaMcpError("symbols must be a non-empty list of okama tickers")
    return ok.AssetList(
        symbols,
        ccy=ccy,
        first_date=first_date,
        last_date=last_date,
        inflation=inflation,
    )


@translates_okama_errors
def compare_assets(
    symbols: list[str],
    ccy: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    inflation: bool = True,
) -> dict[str, Any]:
    """Compare several assets side-by-side.

    Returns okama's ``describe()`` table (CAGR, risk, drawdowns over 1/5/10-year
    windows and since inception) plus the joint date range and the chosen base
    currency.

    Parameters
    ----------
    symbols : list[str]
        Two or more okama tickers, e.g. ['GLD.US', 'VNQ.US'].
    ccy : str, default 'USD'
        Base currency for all metrics.
    first_date, last_date : str, optional
        ISO 'YYYY-MM' bounds.
    inflation : bool, default True
        Include the inflation series in ``describe()`` (limits date range by ~1 month).
    """
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation)
    desc = al.describe()
    return {
        "symbols": list(getattr(al, "symbols", symbols)),
        "ccy": getattr(al, "currency", ccy),
        "first_date": value_to_json(getattr(al, "first_date", None)),
        "last_date": value_to_json(getattr(al, "last_date", None)),
        "describe": dataframe_to_json(desc),
    }


@translates_okama_errors
def get_correlations(
    symbols: list[str],
    ccy: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    inflation: bool = True,
) -> dict[str, Any]:
    """Return the correlation matrix of monthly returns for the given assets.

    The inflation series, if present, is dropped before computing correlations —
    correlations between returns and inflation are rarely actionable, and
    including it pollutes the matrix with a single near-constant series.
    """
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation)
    ror = al.assets_ror

    inflation_label = getattr(al, "inflation", None)
    if inflation_label and inflation_label in ror.columns:
        ror = ror.drop(columns=[inflation_label])

    corr = ror.corr()
    return {
        "symbols": list(getattr(al, "symbols", symbols)),
        "ccy": getattr(al, "currency", ccy),
        "correlations": dataframe_to_json(corr),
    }


def register(mcp: FastMCP) -> None:
    """Register asset-list tools with the FastMCP server."""
    mcp.tool(compare_assets)
    mcp.tool(get_correlations)
