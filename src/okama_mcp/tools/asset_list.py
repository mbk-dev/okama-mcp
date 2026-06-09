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
    rf_return: float = 0.0,
    t_return: float = 0.0,
) -> dict[str, Any]:
    """Compare several assets side-by-side.

    Returns okama's ``describe()`` table (CAGR, risk, drawdowns over 1/5/10-year
    windows and since inception) plus the joint date range and the chosen base
    currency. ``rf_return`` and ``t_return`` control the Sharpe and Sortino ratios.

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
    sharpe = al.get_sharpe_ratio(rf_return=rf_return)
    sortino = al.get_sortino_ratio(t_return=t_return)
    return {
        "symbols": list(getattr(al, "symbols", symbols)),
        "ccy": getattr(al, "currency", ccy),
        "first_date": value_to_json(getattr(al, "first_date", None)),
        "last_date": value_to_json(getattr(al, "last_date", None)),
        "describe": dataframe_to_json(desc),
        "sharpe_ratio": {str(k): value_to_json(v) for k, v in sharpe.items()},
        "sortino_ratio": {str(k): value_to_json(v) for k, v in sortino.items()},
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


@translates_okama_errors
def get_benchmark_metrics(
    benchmark: str,
    symbols: list[str],
    ccy: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    portfolios: list[dict[str, Any]] | None = None,
    rolling_window: int | None = None,
) -> dict[str, Any]:
    """Metrics of each asset relative to a benchmark/index.

    Builds an AssetList with ``benchmark`` first (okama treats the first symbol as
    the index), then ``symbols`` and any nested ``portfolios``. Returns the latest
    value per asset of: beta, correlation with the index, annualized tracking
    difference, and tracking error. ``rolling_window`` (months, >= 12) switches
    okama to a moving window; the response still reports the most recent row.
    """
    if not benchmark:
        raise OkamaMcpError("benchmark must be a non-empty okama ticker")
    al = _build_asset_list(
        [benchmark, *symbols], ccy, first_date, last_date, inflation=False, portfolios=portfolios
    )

    def _last_row(df: Any) -> dict[str, Any]:
        if df is None or len(df) == 0:
            return {}
        return {str(k): value_to_json(v) for k, v in df.iloc[-1].items()}

    return {
        "benchmark": benchmark,
        "ccy": getattr(al, "currency", ccy),
        "rolling_window": rolling_window,
        "beta": _last_row(al.index_beta(rolling_window=rolling_window)),
        "correlation": _last_row(al.index_corr(rolling_window=rolling_window)),
        "tracking_difference_annualized": _last_row(
            al.tracking_difference_annualized(rolling_window=rolling_window)
        ),
        "tracking_error": _last_row(al.tracking_error(rolling_window=rolling_window)),
    }


@translates_okama_errors
def get_asset_returns(
    symbols: list[str],
    ccy: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    inflation: bool = True,
    portfolios: list[dict[str, Any]] | None = None,
    period: int | None = None,
    real: bool = False,
) -> dict[str, Any]:
    """Return metrics for each asset (and any nested ``portfolios``).

    Scalar metrics are the latest (since-inception) value: ``cagr`` and
    ``cumulative_return`` are the last row of okama's expanding series;
    ``mean_return``/``real_mean_return``/``monthly_geom_mean`` are annualized
    per-asset values. ``annual_returns`` is the per-calendar-year return table.
    ``real=True`` returns inflation-adjusted CAGR/cumulative return (needs
    ``inflation=True``); ``period`` limits CAGR to the last N years.
    """
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)

    def _last_row(df: Any) -> dict[str, Any]:
        if df is None or len(df) == 0:
            return {}
        return {str(k): value_to_json(v) for k, v in df.iloc[-1].items()}

    def _series(s: Any) -> dict[str, Any]:
        return {str(k): value_to_json(v) for k, v in s.items()}

    return {
        "ccy": getattr(al, "currency", ccy),
        "period": period,
        "real": real,
        "cagr": _last_row(al.get_cagr(period=period, real=real)),
        "cumulative_return": _last_row(al.get_cumulative_return(real=real)),
        "mean_return": _series(al.mean_return),
        "real_mean_return": _series(al.real_mean_return),
        "monthly_geom_mean": _series(al.get_monthly_geometric_mean_return()),
        "annual_returns": dataframe_to_json(al.annual_return_ts),
    }


@translates_okama_errors
def get_rolling_returns(
    symbols: list[str],
    ccy: str = "USD",
    window_months: int = 12,
    real: bool = False,
    first_date: str | None = None,
    last_date: str | None = None,
    portfolios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rolling CAGR and rolling cumulative return for each asset.

    ``window_months`` is the moving-window size (okama recommends >= 12).
    ``real=True`` computes inflation-adjusted values (needs ``inflation`` data).
    """
    if window_months < 1:
        raise OkamaMcpError("window_months must be a positive number of months")
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation=real, portfolios=portfolios)
    return {
        "ccy": getattr(al, "currency", ccy),
        "window_months": window_months,
        "real": real,
        "rolling_cagr": dataframe_to_json(al.get_rolling_cagr(window=window_months, real=real)),
        "rolling_cumulative_return": dataframe_to_json(
            al.get_rolling_cumulative_return(window=window_months, real=real)
        ),
    }


def register(mcp: FastMCP) -> None:
    """Register asset-list tools with the FastMCP server."""
    mcp.tool(compare_assets)
    mcp.tool(get_correlations)
    mcp.tool(get_rolling_risk)
    mcp.tool(get_dividend_info)
    mcp.tool(get_benchmark_metrics)
    mcp.tool(get_asset_returns)
    mcp.tool(get_rolling_returns)
