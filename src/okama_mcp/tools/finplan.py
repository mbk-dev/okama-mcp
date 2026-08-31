"""Financial plan tools: a plan is an ordered sequence of portfolio stages.

``okama.FinPlan`` chains stages so the balance a Monte Carlo scenario reaches at
the end of one stage is the balance it starts the next one with. That is the
whole point of the class: a retirement stage is funded by whatever the
accumulation stage produced in that same scenario, not by a percentile of it.

Two tools cover the use case. ``finplan_forecast`` runs the Monte Carlo and
folds every plan-level answer into one payload — wealth bands, terminal
distribution, survival, probability of success and the balance at each stage
boundary — because an AI asking "does this plan work?" needs all of them at
once. ``finplan_backtest`` replays the same plan over real history.

Stage portfolios come from the shared portfolio cache. That is safe: building a
cash-flow strategy does not mutate its parent portfolio, so two stages may hold
the same cached ``Portfolio`` object with different strategies, and ``FinPlan``
reads only ``stage.portfolio.ror``.
"""

from __future__ import annotations

from typing import Any

import okama as ok
from fastmcp import FastMCP
from pydantic import ValidationError

from okama_mcp.cache import SpecCache, make_key
from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.schemas import FinPlanSpec, FinPlanStageSpec
from okama_mcp.serialization import dataframe_to_json, to_json, value_to_json
from okama_mcp.tools.monte_carlo import (
    _build_cashflow_strategy,
    _mc_index_iso,
    _percentile_bands,
    _survival_stats,
    _terminal_stats,
)
from okama_mcp.tools.portfolio import _get_portfolio

_DISCOUNTING = ("fv", "pv")

# Module-level cache shared across all plan tools. A FinPlan holds its simulated
# scenarios internally, so a cached plan means the forecast tool and the chart
# tool do not simulate the same plan twice.
_plan_cache: SpecCache = SpecCache(max_size=32, ttl_seconds=3600.0)


def clear_cache() -> None:
    """Drop all cached FinPlan objects (used by tests)."""
    _plan_cache.clear()


def _validate(spec: dict[str, Any]) -> FinPlanSpec:
    try:
        return FinPlanSpec.model_validate(spec)
    except ValidationError as exc:
        raise OkamaMcpError(f"Invalid financial plan spec: {exc.errors()}") from exc


def _check_discounting(discounting: str) -> str:
    if discounting not in _DISCOUNTING:
        raise OkamaMcpError(f"discounting must be one of {_DISCOUNTING}, got {discounting!r}")
    return discounting


def _build_stage(stage_spec: FinPlanStageSpec) -> Any:
    """Build one okama.FinPlanStage from its spec.

    The cash-flow strategy must be built on the very portfolio the stage holds:
    ``FinPlanStage`` rejects a strategy whose ``parent`` is a different object,
    because ``indexation='inflation'`` would otherwise resolve against another
    portfolio's inflation series.
    """
    _, pf = _get_portfolio(stage_spec.portfolio.model_dump())
    strategy = _build_cashflow_strategy(pf, stage_spec.cashflow) if stage_spec.cashflow is not None else None
    return ok.FinPlanStage(
        portfolio=pf,
        period=stage_spec.period_years,
        cashflow_parameters=strategy,
        name=stage_spec.name,
        distribution=stage_spec.distribution,
        distribution_parameters=(
            tuple(stage_spec.distribution_parameters)
            if stage_spec.distribution_parameters is not None
            else None
        ),
    )


def _build_plan(spec: FinPlanSpec) -> Any:
    return ok.FinPlan(
        stages=[_build_stage(stage) for stage in spec.stages],
        initial_investment=spec.initial_investment,
        discount_rate=spec.discount_rate,
        mc_number=spec.scenarios,
        seed=spec.random_seed,
        name=spec.name,
    )


def _get_plan(spec_dict: dict[str, Any]) -> tuple[FinPlanSpec, Any]:
    """Validate the spec and return a (possibly cached) FinPlan object."""
    spec = _validate(spec_dict)
    key = make_key(spec.model_dump())
    plan = _plan_cache.get_or_compute(key, lambda: _build_plan(spec))
    return spec, plan


def _stage_summary(spec: FinPlanSpec) -> list[dict[str, Any]]:
    return [
        {
            "name": stage.name or f"stage {number}",
            "period_years": stage.period_years,
            "distribution": stage.distribution,
            "cashflow_type": stage.cashflow.type if stage.cashflow is not None else None,
        }
        for number, stage in enumerate(spec.stages, start=1)
    ]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@translates_okama_errors
def finplan_forecast(
    plan: dict[str, Any],
    success_threshold: float = 0.0,
) -> dict[str, Any]:
    """Monte Carlo forecast of a multi-stage financial plan.

    A plan is a sequence of stages, each with its own portfolio, horizon and
    cash-flow regime. Scenarios are chained: the balance a scenario ends a stage
    with is the balance it starts the next stage with, so the answer accounts
    for the accumulation stage actually funding the retirement stage.

    Parameters
    ----------
    plan : dict
        :class:`FinPlanSpec` — ``stages`` (each a portfolio + ``period_years`` +
        optional ``cashflow``), plus ``initial_investment``, ``scenarios``,
        ``random_seed`` and reported ``percentiles``.
    success_threshold : float, default 0.0
        Balance, in the plan's currency, a scenario must reach the end of the
        plan with to count as a success. 0.0 means "not depleted".

    Returns
    -------
    dict with ``stages`` (echo of the plan structure), ``wealth_paths``
    (percentile bands over time), ``terminal_wealth``, ``survival``, ``success``
    (share of scenarios finishing above ``success_threshold``),
    ``stage_boundaries`` (balance distribution at each stage transition and at
    the end) and ``irr``.
    """
    spec, plan_obj = _get_plan(plan)

    wealth = plan_obj.monte_carlo_wealth(discounting="fv", include_negative_values=True)
    survival = plan_obj.monte_carlo_survival_period(threshold=0)
    irr_series = plan_obj.monte_carlo_irr()
    probability = float(plan_obj.probability_of_success(threshold=success_threshold))
    boundaries = plan_obj.balance_percentiles(percentiles=tuple(spec.percentiles), discounting="fv")

    return {
        "plan_spec": plan,
        "stages": _stage_summary(spec),
        "total_period_years": sum(stage.period_years for stage in spec.stages),
        "wealth_paths": {
            "index": _mc_index_iso(wealth),
            "percentiles": _percentile_bands(wealth, spec.percentiles),
            "n_scenarios": int(wealth.shape[1]),
            "n_months": int(wealth.shape[0]),
        },
        "terminal_wealth": _terminal_stats(wealth),
        "survival": _survival_stats(wealth, survival),
        "success": {
            "threshold": success_threshold,
            "probability_pct": round(100.0 * probability, 4),
        },
        "stage_boundaries": dataframe_to_json(boundaries, full=True),
        "irr": {
            "percentiles": {
                str(p): value_to_json(float(irr_series.quantile(p / 100.0)))
                for p in sorted(spec.percentiles)
            },
            "mean": value_to_json(float(irr_series.mean())),
        },
    }


@translates_okama_errors
def finplan_backtest(
    plan: dict[str, Any],
    discounting: str = "fv",
    first_date: str | None = None,
) -> dict[str, Any]:
    """Replay a multi-stage financial plan over actual history.

    The stages divide the common history window sequentially: stage one runs on
    its portfolio's real returns for its own length, stage two continues from
    the balance stage one reached. This is a glide-path backtest, not a
    forecast — for the forecast use ``finplan_forecast``.

    Parameters
    ----------
    plan : dict
        :class:`FinPlanSpec`, the same shape ``finplan_forecast`` takes.
    discounting : {'fv', 'pv'}, default 'fv'
        'fv' reports nominal values, 'pv' discounts them to the window start.
    first_date : str, optional
        'YYYY-MM' start of the window. By default the plan starts at the
        earliest date covered by every stage portfolio.

    Returns
    -------
    dict with ``wealth_index`` (plan balance plus accumulated inflation) and
    ``cash_flow`` (monthly contributions and withdrawals), both truncated when
    long.
    """
    _check_discounting(discounting)
    spec, plan_obj = _get_plan(plan)
    wealth = plan_obj.wealth_index(discounting=discounting, first_date=first_date)
    cash_flow = plan_obj.cash_flow_ts(discounting=discounting, first_date=first_date)
    return {
        "plan_spec": plan,
        "stages": _stage_summary(spec),
        "discounting": discounting,
        "wealth_index": to_json(wealth),
        "cash_flow": to_json(cash_flow),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register the financial-plan tools with the FastMCP server."""
    mcp.tool(finplan_forecast)
    mcp.tool(finplan_backtest)
