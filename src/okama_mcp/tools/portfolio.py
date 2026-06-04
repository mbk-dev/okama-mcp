"""Portfolio backtest tools: analyze_portfolio, drawdowns, var/cvar, wealth_index.

Each tool accepts the same ``PortfolioSpec`` dict so the LLM passes a single
self-contained portfolio definition with every call. Constructed
``okama.Portfolio`` objects are cached by the canonical hash of the spec — a
typical AI conversation calls four or five tools against the same portfolio in
a row, and the constructor is expensive (HTTP + pandas).
"""

from __future__ import annotations

from typing import Any

import okama as ok
from fastmcp import FastMCP
from pydantic import ValidationError

from okama_mcp.cache import SpecCache, make_key
from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.schemas import PortfolioSpec
import pandas as pd

from okama_mcp.serialization import (
    dataframe_to_json,
    series_to_json,
    value_to_json,
)


def _scalar_last(value: Any) -> Any:
    """Reduce a pandas Series to its final value; pass scalars through.

    ``Portfolio.risk_annual`` and similar expanding-window properties return a
    Series. The "headline" annual figure is its last entry.
    """
    if isinstance(value, pd.Series):
        return value.iloc[-1] if len(value) else None
    return value

# Module-level cache shared across all portfolio tools.
_portfolio_cache: SpecCache = SpecCache(max_size=64, ttl_seconds=3600.0)


def clear_cache() -> None:
    """Drop all cached Portfolio objects (used by tests)."""
    _portfolio_cache.clear()


def _validate(spec: dict[str, Any]) -> PortfolioSpec:
    try:
        return PortfolioSpec.model_validate(spec)
    except ValidationError as exc:
        raise OkamaMcpError(f"Invalid portfolio spec: {exc.errors()}") from exc


def _build_portfolio(spec: PortfolioSpec) -> Any:
    rebalance = ok.Rebalance(period=spec.rebalancing_period)
    return ok.Portfolio(
        assets=list(spec.assets),
        weights=list(spec.weights) if spec.weights is not None else None,
        ccy=spec.ccy,
        first_date=spec.first_date,
        last_date=spec.last_date,
        inflation=spec.inflation,
        rebalancing_strategy=rebalance,
        symbol=spec.symbol,
    )


def _get_portfolio(spec_dict: dict[str, Any]) -> tuple[PortfolioSpec, Any]:
    """Validate the spec and return a (possibly cached) Portfolio object."""
    spec = _validate(spec_dict)
    key = make_key(spec.model_dump())
    pf = _portfolio_cache.get_or_compute(key, lambda: _build_portfolio(spec))
    return spec, pf


def _weights_dict(pf: Any, spec: PortfolioSpec) -> dict[str, float]:
    # Avoid `or` chains — Portfolio.weights may be a numpy array, whose truth
    # value is ambiguous. Pick the first non-None source explicitly.
    pf_weights = getattr(pf, "weights", None)
    if pf_weights is not None:
        weights = list(pf_weights)
    elif spec.weights is not None:
        weights = list(spec.weights)
    else:
        n = len(spec.assets)
        weights = [1.0 / n] * n
    return {symbol: value_to_json(w) for symbol, w in zip(spec.assets, weights, strict=False)}


def _scalar_cagr(pf: Any) -> float | None:
    """Extract the headline CAGR (inception) from ``Portfolio.get_cagr()``.

    ``get_cagr()`` returns a DataFrame; the first column is the portfolio's own
    CAGR and other columns may include inflation. We take the portfolio column.
    """
    try:
        df = pf.get_cagr()
    except Exception:  # noqa: BLE001 — fall through to None for robustness
        return None
    try:
        portfolio_symbol = getattr(pf, "symbol", None)
        if portfolio_symbol and portfolio_symbol in df.columns:
            return value_to_json(float(df[portfolio_symbol].iloc[-1]))
        return value_to_json(float(df.iloc[-1, 0]))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@translates_okama_errors
def analyze_portfolio(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Backtest summary for a portfolio: CAGR, risk, drawdowns, describe table.

    ``portfolio`` must match :class:`PortfolioSpec`: ``assets`` plus optional
    ``weights`` (must sum to 1.0), ``ccy``, ``first_date``, ``last_date``,
    ``rebalancing_period`` (default 'year'), ``inflation`` (default True).
    """
    spec, pf = _get_portfolio(portfolio)
    return {
        "spec": spec.model_dump(),
        "weights": _weights_dict(pf, spec),
        "ccy": getattr(pf, "currency", spec.ccy),
        "first_date": value_to_json(getattr(pf, "first_date", None)),
        "last_date": value_to_json(getattr(pf, "last_date", None)),
        "period_years": value_to_json(getattr(pf, "period_length", None)),
        "metrics": {
            "cagr": _scalar_cagr(pf),
            "mean_return_annual": value_to_json(
                _scalar_last(getattr(pf, "mean_return_annual", None))
            ),
            "risk_annual": value_to_json(_scalar_last(getattr(pf, "risk_annual", None))),
        },
        "describe": dataframe_to_json(pf.describe()),
    }


@translates_okama_errors
def get_portfolio_drawdowns(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Drawdown time series for a portfolio plus headline max-drawdown stats.

    Drawdown is the percentage decline from a previous peak in the wealth index.
    """
    _spec, pf = _get_portfolio(portfolio)
    dd_series = pf.drawdowns
    recovery = getattr(pf, "recovery_period", None)

    max_dd = value_to_json(float(dd_series.min())) if len(dd_series) else None
    max_recovery = (
        value_to_json(int(recovery.max())) if recovery is not None and len(recovery) else None
    )

    out: dict[str, Any] = {
        "max_drawdown": max_dd,
        "max_recovery_months": max_recovery,
        "drawdowns": series_to_json(dd_series),
    }
    if recovery is not None:
        out["recovery_period"] = series_to_json(recovery)
    return out


@translates_okama_errors
def get_portfolio_var_cvar(
    portfolio: dict[str, Any],
    time_frame: int = 12,
    level: int = 1,
) -> dict[str, Any]:
    """Historical Value at Risk and Conditional VaR for the portfolio.

    Parameters
    ----------
    time_frame : int, default 12
        Rolling window in months over which losses are measured.
    level : int, default 1
        Confidence level in percent (1 = 1% tail). Must be in [0, 100].
    """
    if level < 0 or level > 100:
        raise OkamaMcpError(f"level must be in [0, 100], got {level}")
    if time_frame < 1:
        raise OkamaMcpError(f"time_frame must be >= 1 month, got {time_frame}")

    _spec, pf = _get_portfolio(portfolio)
    var = pf.get_var_historic(time_frame=time_frame, level=level)
    cvar = pf.get_cvar_historic(time_frame=time_frame, level=level)
    return {
        "var": value_to_json(var),
        "cvar": value_to_json(cvar),
        "time_frame_months": time_frame,
        "level_percent": level,
    }


@translates_okama_errors
def get_portfolio_wealth_index(
    portfolio: dict[str, Any],
    full: bool = False,
) -> dict[str, Any]:
    """Wealth-index time series for the portfolio (cumulative growth of 1000).

    okama returns a DataFrame: the portfolio column plus an accumulated-inflation
    column when the spec has ``inflation: true``.
    """
    _spec, pf = _get_portfolio(portfolio)
    wi = pf.wealth_index
    return {
        "currency": getattr(pf, "currency", None),
        "wealth_index": dataframe_to_json(wi, full=full),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register Phase 4 portfolio tools with the FastMCP server."""
    mcp.tool(analyze_portfolio)
    mcp.tool(get_portfolio_drawdowns)
    mcp.tool(get_portfolio_var_cvar)
    mcp.tool(get_portfolio_wealth_index)
