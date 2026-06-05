"""Monte Carlo DCF forecast tool.

This is the centrepiece of the retirement-planning use case: given a portfolio,
a Monte Carlo configuration, and a cashflow strategy (withdrawals/contributions
schedule), simulate N future wealth paths and return digestible statistics —
percentile bands of wealth over time, terminal-wealth distribution, and
survival metrics.

Critically we do **not** return the full N_months × N_scenarios matrix. For a
typical 25-year × 500-scenario run that's 150_000 floats. We compress to the
percentiles the caller asked for (default 5/50/95) plus scalars.
"""

from __future__ import annotations

from typing import Any

import okama as ok
import pandas as pd
from fastmcp import FastMCP
from pydantic import ValidationError

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.schemas import (
    CashflowAdapter,
    CutIfDrawdownCashflow,
    IndexationCashflow,
    MCSpec,
    PercentageCashflow,
    TimeSeriesCashflow,
    VanguardDynamicCashflow,
)
from okama_mcp.serialization import series_to_json, value_to_json
from okama_mcp.tools.portfolio import _get_portfolio


def _validate_mc(spec: dict[str, Any]) -> MCSpec:
    try:
        return MCSpec.model_validate(spec)
    except ValidationError as exc:
        raise OkamaMcpError(f"Invalid MC spec: {exc.errors()}") from exc


def _validate_cashflow(spec: dict[str, Any]) -> Any:
    try:
        return CashflowAdapter.validate_python(spec)
    except ValidationError as exc:
        raise OkamaMcpError(f"Invalid cashflow spec: {exc.errors()}") from exc


def _build_cashflow_strategy(pf: Any, cashflow: Any) -> Any:
    """Construct the okama cashflow-strategy instance bound to ``pf``."""
    if isinstance(cashflow, IndexationCashflow):
        strat = ok.IndexationStrategy(pf)
        strat.initial_investment = cashflow.initial_investment
        strat.frequency = cashflow.frequency
        strat.amount = cashflow.amount
        strat.indexation = cashflow.indexation
        return strat

    if isinstance(cashflow, PercentageCashflow):
        strat = ok.PercentageStrategy(pf)
        strat.initial_investment = cashflow.initial_investment
        strat.frequency = cashflow.frequency
        strat.percentage = cashflow.percentage
        return strat

    if isinstance(cashflow, TimeSeriesCashflow):
        strat = ok.TimeSeriesStrategy(pf)
        strat.initial_investment = cashflow.initial_investment
        strat.time_series_dic = dict(cashflow.events)
        return strat

    if isinstance(cashflow, VanguardDynamicCashflow):
        return ok.VanguardDynamicSpending(
            parent=pf,
            initial_investment=cashflow.initial_investment,
            percentage=cashflow.percentage,
            min_max_annual_withdrawals=(
                tuple(cashflow.min_max_annual_withdrawals)
                if cashflow.min_max_annual_withdrawals is not None
                else None
            ),
            adjust_min_max=cashflow.adjust_min_max,
            floor_ceiling=(
                tuple(cashflow.floor_ceiling)
                if cashflow.floor_ceiling is not None
                else None
            ),
            adjust_floor_ceiling=cashflow.adjust_floor_ceiling,
            indexation=cashflow.indexation,
        )

    if isinstance(cashflow, CutIfDrawdownCashflow):
        return ok.CutWithdrawalsIfDrawdown(
            parent=pf,
            frequency=cashflow.frequency,
            initial_investment=cashflow.initial_investment,
            amount=cashflow.amount,
            indexation=cashflow.indexation,
            crash_threshold_reduction=[tuple(pair) for pair in cashflow.crash_threshold_reduction],
        )

    raise OkamaMcpError(f"Unsupported cashflow type: {type(cashflow).__name__}")


def _percentile_bands(
    mc_wealth: pd.DataFrame, percentiles: list[int]
) -> dict[str, dict[str, Any]]:
    """For each percentile p in [0..100], compute its time series across scenarios."""
    bands: dict[str, dict[str, Any]] = {}
    for p in percentiles:
        series = mc_wealth.quantile(p / 100.0, axis=1)
        bands[str(p)] = series_to_json(series, full=True)
    return bands


def _terminal_stats(mc_wealth: pd.DataFrame) -> dict[str, Any]:
    final_row = mc_wealth.iloc[-1].dropna()
    if final_row.empty:
        return {"min": None, "max": None, "mean": None, "median": None, "count": 0}
    return {
        "count": int(final_row.size),
        "min": value_to_json(float(final_row.min())),
        "max": value_to_json(float(final_row.max())),
        "mean": value_to_json(float(final_row.mean())),
        "median": value_to_json(float(final_row.median())),
        "p5": value_to_json(float(final_row.quantile(0.05))),
        "p50": value_to_json(float(final_row.quantile(0.50))),
        "p95": value_to_json(float(final_row.quantile(0.95))),
    }


def _survival_stats(mc_wealth: pd.DataFrame, survival: pd.Series) -> dict[str, Any]:
    final_row = mc_wealth.iloc[-1]
    total = int(final_row.size)
    above_zero = int((final_row > 0).sum())
    above_zero_pct = round(100.0 * above_zero / total, 4) if total else None

    survival = pd.Series(survival).dropna()
    return {
        "scenarios_above_zero_pct": above_zero_pct,
        "min_survival_years": value_to_json(float(survival.min())) if len(survival) else None,
        "median_survival_years": value_to_json(float(survival.median())) if len(survival) else None,
        "max_survival_years": value_to_json(float(survival.max())) if len(survival) else None,
        "p5_survival_years": value_to_json(float(survival.quantile(0.05))) if len(survival) else None,
    }


def _mc_index_iso(mc_wealth: pd.DataFrame) -> list[str]:
    idx = mc_wealth.index
    if isinstance(idx, pd.PeriodIndex):
        return [ts.strftime("%Y-%m-%d") for ts in idx.to_timestamp(how="end").normalize()]
    if isinstance(idx, pd.DatetimeIndex):
        return [ts.strftime("%Y-%m-%d") for ts in idx]
    return [str(v) for v in idx]


def _prepare_dcf(
    portfolio: dict[str, Any], mc: dict[str, Any], cashflow: dict[str, Any]
) -> tuple[Any, MCSpec]:
    """Validate specs and return (Portfolio configured for MC, validated MCSpec)."""
    mc_spec = _validate_mc(mc)
    cashflow_spec = _validate_cashflow(cashflow)
    _, pf = _get_portfolio(portfolio)

    pf.dcf.set_mc_parameters(
        distribution=mc_spec.distribution,
        period=mc_spec.period_years,
        mc_number=mc_spec.scenarios,
        seed=mc_spec.random_seed,
    )
    strategy = _build_cashflow_strategy(pf, cashflow_spec)
    pf.dcf.cashflow_parameters = strategy
    return pf, mc_spec


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@translates_okama_errors
def get_portfolio_irr(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
) -> dict[str, Any]:
    """Historical money-weighted return (IRR) of the portfolio with a cash-flow plan.

    Unlike CAGR (time-weighted), IRR reflects the investor's actual experience with
    the given contributions/withdrawals schedule. Returns null when the cash flow
    has no sign change (IRR undefined). Requires okama >= 2.2.0.

    Parameters
    ----------
    portfolio : dict
        :class:`PortfolioSpec` — assets + weights + dates + base currency.
    cashflow : dict
        :class:`CashflowSpec` — one of indexation / percentage / time_series /
        vanguard / cut_if_drawdown. The ``type`` field discriminates.

    Returns
    -------
    dict with ``irr`` (float or None) and ``cashflow_spec``.
    """
    cashflow_spec = _validate_cashflow(cashflow)
    _, pf = _get_portfolio(portfolio)
    strategy = _build_cashflow_strategy(pf, cashflow_spec)
    pf.dcf.cashflow_parameters = strategy
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "irr": value_to_json(float(pf.dcf.irr())),
    }


@translates_okama_errors
def monte_carlo_forecast(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    cashflow: dict[str, Any],
) -> dict[str, Any]:
    """Forward-looking Monte Carlo forecast for a portfolio with cash flows.

    Parameters
    ----------
    portfolio : dict
        :class:`PortfolioSpec` — assets + weights + dates + base currency.
    mc : dict
        :class:`MCSpec` — distribution ('norm'/'lognorm'/'t'), ``period_years``,
        ``scenarios`` (≤5000), reported percentiles, optional ``random_seed``.
    cashflow : dict
        :class:`CashflowSpec` — one of indexation / percentage / time_series /
        vanguard / cut_if_drawdown. The ``type`` field discriminates.

    Returns
    -------
    dict with ``wealth_paths`` (percentile bands over time), ``terminal_wealth``
    (distribution stats of final values), and ``survival`` (% of scenarios with
    positive terminal wealth, plus survival-period quantiles in years).
    """
    pf, mc_spec = _prepare_dcf(portfolio, mc, cashflow)

    mc_wealth = pf.dcf.monte_carlo_wealth(discounting="fv", include_negative_values=True)
    survival = pf.dcf.monte_carlo_survival_period(threshold=0)
    irr_series = pf.dcf.monte_carlo_irr()

    return {
        "portfolio_spec": portfolio,
        "mc_spec": mc_spec.model_dump(),
        "cashflow_spec": _validate_cashflow(cashflow).model_dump(),
        "wealth_paths": {
            "index": _mc_index_iso(mc_wealth),
            "percentiles": _percentile_bands(mc_wealth, mc_spec.percentiles),
            "n_scenarios": int(mc_wealth.shape[1]),
            "n_months": int(mc_wealth.shape[0]),
        },
        "terminal_wealth": _terminal_stats(mc_wealth),
        "survival": _survival_stats(mc_wealth, survival),
        "irr": {
            "percentiles": {
                str(p): value_to_json(float(irr_series.quantile(p / 100.0)))
                for p in sorted(mc_spec.percentiles)
            },
            "mean": value_to_json(float(irr_series.mean())),
        },
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register Phase 5 Monte Carlo tools with the FastMCP server."""
    mcp.tool(get_portfolio_irr)
    mcp.tool(monte_carlo_forecast)
