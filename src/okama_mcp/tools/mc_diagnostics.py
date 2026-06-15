"""Monte Carlo distribution-fit diagnostics.

These tools read the portfolio's historical returns and the fitted distribution
(``pf.dcf.mc``); they do NOT require a cashflow strategy. Each accepts a full
PortfolioSpec + MCSpec — distribution and (optional) distribution_parameters drive
the goodness-of-fit numbers.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from okama_mcp.errors import translates_okama_errors
from okama_mcp.serialization import dataframe_to_json, series_to_json, value_to_json
from okama_mcp.tools.monte_carlo import _prepare_mc


@translates_okama_errors
def get_distribution_fit(portfolio: dict[str, Any], mc: dict[str, Any]) -> dict[str, Any]:
    """Goodness-of-fit diagnostics for the portfolio's return distribution.

    Parameters
    ----------
    portfolio : dict
        :class:`PortfolioSpec`.
    mc : dict
        :class:`MCSpec` — ``distribution`` (and optional ``distribution_parameters``)
        select the theoretical distribution being tested.

    Returns
    -------
    dict with the resolved (fitted) ``parameters`` tuple, ``jarque_bera`` (normality),
    ``kstest`` (Kolmogorov-Smirnov for the chosen distribution),
    ``kstest_all_distributions`` (KS for norm/lognorm/t), and ``backtesting_error``
    (theoretical-vs-empirical mean/VaR/CVaR deltas).
    """
    pf, mc_spec = _prepare_mc(portfolio, mc)
    m = pf.dcf.mc
    return {
        "mc_spec": mc_spec.model_dump(),
        "distribution": mc_spec.distribution,
        "parameters": [value_to_json(float(p)) for p in m.get_parameters_for_distribution()],
        "jarque_bera": {k: value_to_json(v) for k, v in m.jarque_bera.items()},
        "kstest": {k: value_to_json(v) for k, v in m.kstest.items()},
        "kstest_all_distributions": dataframe_to_json(m.kstest_for_all_distributions, full=True),
        "backtesting_error": {k: value_to_json(v) for k, v in m.backtesting_error().items()},
    }


@translates_okama_errors
def get_return_moments(
    portfolio: dict[str, Any], mc: dict[str, Any], rolling_window: int | None = None
) -> dict[str, Any]:
    """Skewness and kurtosis time series for the portfolio's returns.

    With ``rolling_window=None`` (default) returns the expanding-window series;
    pass a window in months (>=12) for the rolling version. Long series are
    truncated to head/tail/summary.
    """
    pf, mc_spec = _prepare_mc(portfolio, mc)
    m = pf.dcf.mc
    if rolling_window is None:
        skew, kurt = m.skewness, m.kurtosis
    else:
        skew = m.skewness_rolling(window=rolling_window)
        kurt = m.kurtosis_rolling(window=rolling_window)
    return {
        "mc_spec": mc_spec.model_dump(),
        "rolling_window": rolling_window,
        "skewness": series_to_json(skew),
        "kurtosis": series_to_json(kurt),
    }


@translates_okama_errors
def optimize_students_df(
    portfolio: dict[str, Any], mc: dict[str, Any], var_level: int = 5
) -> dict[str, Any]:
    """Degrees of freedom for a Student-t that best matches empirical VaR/CVaR.

    ``var_level`` is the tail percent (1..99, default 5). Useful for choosing the
    ``df`` to pass back in ``MCSpec.distribution_parameters`` for a t-distribution.
    """
    pf, mc_spec = _prepare_mc(portfolio, mc)
    df = pf.dcf.mc.optimize_df_for_students(var_level=var_level)
    return {
        "mc_spec": mc_spec.model_dump(),
        "var_level": var_level,
        "degrees_of_freedom": value_to_json(float(df)),
    }


@translates_okama_errors
def get_cagr_distribution(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    percentiles: list[int] | None = None,
    score: float = 0.0,
) -> dict[str, Any]:
    """Simulated CAGR distribution from the Monte Carlo paths.

    ``percentiles`` (default [10, 50, 90]) -> the CAGR at each percentile.
    ``score`` (default 0.0) -> ``prob_below_score_pct``: the share of simulated
    CAGRs at or below ``score`` (e.g. score=0 = probability of a negative result).
    """
    if percentiles is None:
        percentiles = [10, 50, 90]
    pf, mc_spec = _prepare_mc(portfolio, mc)
    m = pf.dcf.mc
    dist = m.percentile_distribution_cagr(percentiles=list(percentiles))
    rank = m.percentile_inverse_cagr(score=score)
    return {
        "mc_spec": mc_spec.model_dump(),
        "percentiles": {str(k): value_to_json(float(v)) for k, v in dist.items()},
        "score": value_to_json(float(score)),
        "prob_below_score_pct": value_to_json(float(rank)),
    }


def register(mcp: FastMCP) -> None:
    """Register MC distribution-diagnostics tools."""
    mcp.tool(get_distribution_fit)
    mcp.tool(get_return_moments)
    mcp.tool(optimize_students_df)
    mcp.tool(get_cagr_distribution)
