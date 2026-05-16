"""Efficient Frontier tools: build_efficient_frontier, tangency, min-variance.

Three closely-related tools share one cached ``ok.EfficientFrontier`` per spec —
the optimiser is the expensive part, so once we've built the frontier we want
to read tangency and GMV portfolios off it without re-running n_points×SLSQP
optimisations.
"""

from __future__ import annotations

from typing import Any

import okama as ok
from fastmcp import FastMCP
from pydantic import ValidationError

from okama_mcp.cache import SpecCache, make_key
from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.schemas import FrontierSpec
from okama_mcp.serialization import dataframe_to_json, value_to_json

_VALID_ROR_KINDS = ("cagr", "mean_return")

_frontier_cache: SpecCache = SpecCache(max_size=32, ttl_seconds=3600.0)


def clear_cache() -> None:
    """Drop all cached frontier objects (used by tests)."""
    _frontier_cache.clear()


def _validate(spec: dict[str, Any]) -> FrontierSpec:
    try:
        return FrontierSpec.model_validate(spec)
    except ValidationError as exc:
        raise OkamaMcpError(f"Invalid frontier spec: {exc.errors()}") from exc


def _bounds_for_okama(bounds: list[list[float]] | None) -> tuple[tuple[float, float], ...] | None:
    if bounds is None:
        return None
    return tuple((float(b[0]), float(b[1])) for b in bounds)


def _build_frontier(spec: FrontierSpec) -> Any:
    return ok.EfficientFrontier(
        assets=list(spec.assets),
        ccy=spec.ccy,
        first_date=spec.first_date,
        last_date=spec.last_date,
        bounds=_bounds_for_okama(spec.bounds),
        inflation=spec.inflation,
        full_frontier=spec.full_frontier,
        n_points=spec.n_points,
        rebalancing_strategy=ok.Rebalance(period=spec.rebalancing_period),
    )


def _get_frontier(spec_dict: dict[str, Any]) -> tuple[FrontierSpec, Any]:
    spec = _validate(spec_dict)
    key = make_key(spec.model_dump())
    ef = _frontier_cache.get_or_compute(key, lambda: _build_frontier(spec))
    return spec, ef


def _weights_dict(symbols: list[str], weights: Any) -> dict[str, float]:
    return {sym: value_to_json(float(w)) for sym, w in zip(symbols, weights, strict=False)}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@translates_okama_errors
def build_efficient_frontier(frontier: dict[str, Any]) -> dict[str, Any]:
    """Build the multi-period Efficient Frontier for a set of assets.

    Returns the EF point table with per-asset weights, annualised Risk
    (standard deviation), Mean return, and CAGR for each point.

    ``frontier`` is a :class:`FrontierSpec` dict: ``assets`` (≥2), ``ccy``,
    optional ``first_date``/``last_date``, optional ``bounds`` as
    ``[[min, max], ...]``, ``n_points`` (default 20), ``rebalancing_period``,
    ``inflation``.
    """
    spec, ef = _get_frontier(frontier)
    return {
        "spec": spec.model_dump(),
        "symbols": list(getattr(ef, "symbols", spec.assets)),
        "ccy": getattr(ef, "currency", spec.ccy),
        "first_date": value_to_json(getattr(ef, "first_date", None)),
        "last_date": value_to_json(getattr(ef, "last_date", None)),
        "ef_points": dataframe_to_json(ef.ef_points),
    }


@translates_okama_errors
def get_tangency_portfolio(
    frontier: dict[str, Any],
    rf_return: float = 0.0,
    rate_of_return: str = "cagr",
) -> dict[str, Any]:
    """Tangency portfolio: max Sharpe ratio on the Efficient Frontier.

    Parameters
    ----------
    rf_return : float, default 0.0
        Risk-free rate of return used to compute the Sharpe ratio.
    rate_of_return : {'cagr', 'mean_return'}, default 'cagr'
        Definition of return used in the objective function. CAGR (geometric
        mean) is the more conservative choice; 'mean_return' uses arithmetic
        mean.
    """
    if rate_of_return not in _VALID_ROR_KINDS:
        raise OkamaMcpError(
            f"rate_of_return must be one of {_VALID_ROR_KINDS}, got {rate_of_return!r}"
        )

    spec, ef = _get_frontier(frontier)
    raw = ef.get_tangency_portfolio(rf_return=rf_return, rate_of_return=rate_of_return)
    symbols = list(getattr(ef, "symbols", spec.assets))
    risk = float(raw["Risk"])
    ror = float(raw["Rate_of_return"])
    sharpe = (ror - rf_return) / risk if risk else None
    return {
        "weights": _weights_dict(symbols, raw["Weights"]),
        "rate_of_return": value_to_json(ror),
        "risk": value_to_json(risk),
        "sharpe_ratio": value_to_json(sharpe),
        "rf_return": value_to_json(rf_return),
        "rate_of_return_kind": rate_of_return,
    }


@translates_okama_errors
def get_min_variance_portfolio(frontier: dict[str, Any]) -> dict[str, Any]:
    """Global Minimum Variance (GMV) portfolio on the Efficient Frontier.

    Annualised values. Use this when you want to minimise risk regardless of
    expected return — the leftmost point of the frontier.
    """
    spec, ef = _get_frontier(frontier)
    symbols = list(getattr(ef, "symbols", spec.assets))
    risk, ror = ef.gmv_annual_values
    return {
        "weights": _weights_dict(symbols, ef.gmv_annual_weights),
        "risk": value_to_json(float(risk)),
        "rate_of_return": value_to_json(float(ror)),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register Phase 6 frontier tools with the FastMCP server."""
    mcp.tool(build_efficient_frontier)
    mcp.tool(get_tangency_portfolio)
    mcp.tool(get_min_variance_portfolio)
