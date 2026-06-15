"""Discounted-cash-flow (DCF) tools over okama.PortfolioDCF.

Historical tools (wealth index, cash flow, survival, initial investment) take a
PortfolioSpec + CashflowSpec and never simulate. The Monte Carlo cash-flow tool
additionally takes an MCSpec and returns percentile bands (never the raw matrix).
``discount_rate`` is optional; when omitted okama's default is used.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from okama_mcp.errors import translates_okama_errors
from okama_mcp.serialization import to_json, value_to_json
from okama_mcp.tools.monte_carlo import (
    _mc_index_iso,
    _percentile_bands,
    _prepare_cashflow,
    _prepare_dcf,
    _validate_cashflow,
)


@translates_okama_errors
def get_dcf_wealth_index(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    discounting: str = "fv",
    include_negative_values: bool = False,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Historical wealth index of the portfolio with a cash-flow plan.

    ``discounting``: 'fv' (nominal) or 'pv' (discounted by ``discount_rate``).
    Returns the portfolio (+ accumulated inflation) wealth series, truncated.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow, discount_rate=discount_rate)
    wi = pf.dcf.wealth_index(discounting=discounting, include_negative_values=include_negative_values)
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "discounting": discounting,
        "wealth_index": to_json(wi),
    }


@translates_okama_errors
def get_dcf_cash_flow_ts(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    discounting: str = "fv",
    remove_if_wealth_index_negative: bool = True,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Historical cash-flow (contributions/withdrawals) time series.

    ``discounting``: 'fv' or 'pv'. ``remove_if_wealth_index_negative`` zeroes the
    cash flow after the portfolio is depleted. Series is truncated.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow, discount_rate=discount_rate)
    cf = pf.dcf.cash_flow_ts(
        discounting=discounting, remove_if_wealth_index_negative=remove_if_wealth_index_negative
    )
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "discounting": discounting,
        "cash_flow": to_json(cf),
    }


@translates_okama_errors
def get_dcf_wealth_with_assets(
    portfolio: dict[str, Any], cashflow: dict[str, Any]
) -> dict[str, Any]:
    """Historical wealth index (FV) for the portfolio AND each underlying asset.

    Adds the accumulated-inflation column when the portfolio has inflation. The
    DataFrame is truncated (head/tail/summary) for long histories.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow)
    df = pf.dcf.wealth_index_fv_with_assets
    return {"cashflow_spec": cashflow_spec.model_dump(), "wealth_index": to_json(df)}


@translates_okama_errors
def get_survival_period(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    threshold: float = 0.0,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Historical portfolio longevity under the cash-flow plan.

    ``threshold`` is the fraction of the initial investment at which the balance
    is considered depleted (relevant for percentage withdrawals). Returns the
    survival period in years and the depletion date.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow, discount_rate=discount_rate)
    period = pf.dcf.survival_period_hist(threshold=threshold)
    date = pf.dcf.survival_date_hist(threshold=threshold)
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "threshold": value_to_json(float(threshold)),
        "survival_period_years": value_to_json(float(period)),
        "survival_date": value_to_json(date),
    }


@translates_okama_errors
def get_initial_investment_values(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Present value (PV) and future value (FV) of the initial investment.

    PV discounts the initial investment to the historical first date using
    ``discount_rate``; FV is the nominal initial investment. Both are ``None`` if
    the strategy has no ``initial_investment``.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow, discount_rate=discount_rate)
    pv = pf.dcf.initial_investment_pv
    fv = pf.dcf.initial_investment_fv
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "discount_rate": value_to_json(pf.dcf.discount_rate),
        "pv": value_to_json(pv) if pv is not None else None,
        "fv": value_to_json(fv) if fv is not None else None,
    }


@translates_okama_errors
def get_monte_carlo_cash_flow(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    cashflow: dict[str, Any],
    discounting: str = "fv",
) -> dict[str, Any]:
    """Monte Carlo distribution of future cash flows over time.

    Returns percentile bands of the simulated cash-flow paths (never the raw
    months x scenarios matrix), mirroring ``monte_carlo_forecast``'s wealth bands.
    """
    pf, mc_spec = _prepare_dcf(portfolio, mc, cashflow)
    mc_cf = pf.dcf.monte_carlo_cash_flow(discounting=discounting)
    return {
        "mc_spec": mc_spec.model_dump(),
        "cashflow_spec": _validate_cashflow(cashflow).model_dump(),
        "discounting": discounting,
        "cash_flow_paths": {
            "index": _mc_index_iso(mc_cf),
            "percentiles": _percentile_bands(mc_cf, mc_spec.percentiles),
            "n_scenarios": int(mc_cf.shape[1]),
            "n_months": int(mc_cf.shape[0]),
        },
    }


def register(mcp: FastMCP) -> None:
    """Register DCF tools."""
    mcp.tool(get_dcf_wealth_index)
    mcp.tool(get_dcf_cash_flow_ts)
    mcp.tool(get_dcf_wealth_with_assets)
    mcp.tool(get_survival_period)
    mcp.tool(get_initial_investment_values)
    mcp.tool(get_monte_carlo_cash_flow)
