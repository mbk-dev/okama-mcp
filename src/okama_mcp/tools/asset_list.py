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
from pydantic import ValidationError

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.schemas import PortfolioSpec
from okama_mcp.serialization import dataframe_to_json, value_to_json
from okama_mcp.tools.portfolio import _build_portfolio


def _build_asset_list(
    symbols: list[str],
    ccy: str,
    first_date: str | None,
    last_date: str | None,
    inflation: bool,
    portfolios: list[dict[str, Any]] | None = None,
) -> Any:
    resolved: list[Any] = list(symbols)
    for raw in portfolios or []:
        try:
            p_spec = PortfolioSpec.model_validate(raw)
        except ValidationError as exc:
            raise OkamaMcpError(f"Invalid portfolio spec: {exc.errors()}") from exc
        resolved.append(_build_portfolio(p_spec))
    if not resolved:
        raise OkamaMcpError("symbols must be a non-empty list of okama tickers")
    return ok.AssetList(
        resolved,
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
    portfolios: list[dict[str, Any]] | None = None,
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
    portfolios : list[dict], optional
        Optional list of portfolio specs to include as components alongside ``symbols``.
    """
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)
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
    portfolios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the correlation matrix of monthly returns for the given assets.

    The inflation series, if present, is dropped before computing correlations —
    correlations between returns and inflation are rarely actionable, and
    including it pollutes the matrix with a single near-constant series.

    Parameters
    ----------
    portfolios : list[dict], optional
        Optional list of portfolio specs to include as components alongside ``symbols``.
    """
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)
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


@translates_okama_errors
def get_rolling_risk(
    symbols: list[str],
    ccy: str,
    window_months: int = 12,
    first_date: str | None = None,
    last_date: str | None = None,
    portfolios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rolling annualized risk (std of monthly returns) for each asset.

    Parameters
    ----------
    portfolios : list[dict], optional
        Optional list of portfolio specs to include as components alongside ``symbols``.
    """
    if window_months < 1:
        raise OkamaMcpError("window_months must be a positive number of months")
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation=False, portfolios=portfolios)
    df = al.get_rolling_risk_annual(window=window_months)
    return {
        "currency": ccy,
        "window_months": window_months,
        "rolling_risk_annual": dataframe_to_json(df),
    }


@translates_okama_errors
def get_dividend_info(
    symbols: list[str],
    ccy: str,
    first_date: str | None = None,
    last_date: str | None = None,
) -> dict[str, Any]:
    """Dividend summary per asset: current LTM yield, 5-year mean yield,
    and the current streaks of dividend-paying / dividend-growing years."""
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation=False)
    ltm = al.dividend_yield.iloc[-1]
    mean5 = al.get_dividend_mean_yield(period=5)
    paying = al.dividend_paying_years.iloc[-1]
    growing = al.dividend_growing_years.iloc[-1]

    def _series_dict(s: Any) -> dict[str, Any]:
        return {str(k): value_to_json(v) for k, v in s.items()}

    return {
        "currency": ccy,
        "ltm_dividend_yield": _series_dict(ltm),
        "mean_yield_5y": _series_dict(mean5),
        "paying_years_streak": {str(k): int(v) for k, v in paying.items()},
        "growing_years_streak": {str(k): int(v) for k, v in growing.items()},
    }


def register(mcp: FastMCP) -> None:
    """Register asset-list tools with the FastMCP server."""
    mcp.tool(compare_assets)
    mcp.tool(get_correlations)
    mcp.tool(get_rolling_risk)
    mcp.tool(get_dividend_info)
