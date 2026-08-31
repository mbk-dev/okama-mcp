"""Tests for tools/finplan.py: multi-stage financial plan forecast and backtest."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from okama_mcp.errors import OkamaMcpError
from okama_mcp.tools import finplan as fp_tool
from okama_mcp.tools import portfolio as pf_tool


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    pf_tool.clear_cache()
    fp_tool.clear_cache()


def _make_mc_wealth(n_months: int = 24, n_scenarios: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed=0)
    idx = pd.period_range("2025-01", periods=n_months, freq="M")
    base = np.linspace(100_000, 250_000, n_months)
    data = {f"s{i}": base * (1 + (i - 1) * 0.1) + rng.normal(0, 100, n_months) for i in range(n_scenarios)}
    return pd.DataFrame(data, index=idx)


def _make_boundaries() -> pd.DataFrame:
    return pd.DataFrame(
        [[90_000.0, 120_000.0, 160_000.0], [10_000.0, 60_000.0, 140_000.0]],
        index=pd.Index(["accumulation", "retirement"], name="stage"),
        columns=["10%", "50%", "90%"],
    )


def _make_plan_mock(*, mc_wealth: pd.DataFrame | None = None) -> SimpleNamespace:
    plan = SimpleNamespace()
    plan.name = "plan"
    plan.period_months = 24
    plan.monte_carlo_wealth = MagicMock(return_value=mc_wealth if mc_wealth is not None else _make_mc_wealth())
    plan.monte_carlo_survival_period = MagicMock(return_value=pd.Series([1.0, 2.0, 2.0, 2.0]))
    plan.monte_carlo_irr = MagicMock(return_value=pd.Series([0.03, 0.05, 0.06, 0.08]))
    plan.probability_of_success = MagicMock(return_value=0.75)
    plan.balance_percentiles = MagicMock(return_value=_make_boundaries())
    plan.wealth_index = MagicMock(
        return_value=pd.DataFrame(
            {"plan": [100.0, 110.0, 120.0], "RUB.INFL": [100.0, 101.0, 102.0]},
            index=pd.period_range("2020-01", periods=3, freq="M"),
        )
    )
    plan.cash_flow_ts = MagicMock(
        return_value=pd.Series(
            [0.0, -1000.0, 0.0], index=pd.period_range("2020-01", periods=3, freq="M"), name="cash_flow"
        )
    )
    return plan


def _make_pf_mock(symbol: str = "pf.PF") -> SimpleNamespace:
    pf = SimpleNamespace()
    pf.symbol = symbol
    pf.symbols = ["GLD.US", "VNQ.US"]
    pf.weights = [0.3, 0.7]
    pf.currency = "USD"
    pf.dcf = SimpleNamespace()
    return pf


ACCUMULATION: dict = {
    "portfolio": {"assets": ["SPY.US", "AGG.US"], "weights": [0.6, 0.4]},
    "period_years": 20,
    "name": "accumulation",
    "cashflow": {
        "type": "indexation",
        "initial_investment": 100_000.0,
        "frequency": "year",
        "amount": 12_000.0,
        "indexation": 0.03,
    },
}

RETIREMENT: dict = {
    "portfolio": {"assets": ["AGG.US"], "weights": [1.0]},
    "period_years": 25,
    "name": "retirement",
    "distribution": "t",
    "distribution_parameters": [5.0, None, None],
    "cashflow": {
        "type": "percentage",
        "initial_investment": 100_000.0,
        "frequency": "year",
        "percentage": -0.04,
    },
}

VALID_PLAN: dict = {
    "stages": [ACCUMULATION, RETIREMENT],
    "initial_investment": 100_000.0,
    "scenarios": 4,
    "random_seed": 7,
    "percentiles": [10, 50, 90],
    "name": "retirement plan",
}


def _patched(plan: SimpleNamespace, pf: SimpleNamespace):
    """Patch okama constructors reached by the finplan tool module."""
    return (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
        patch("okama_mcp.tools.finplan.ok.FinPlan", return_value=plan),
    )


class TestPlanConstruction:
    def test_builds_one_stage_per_spec_entry(self) -> None:
        plan, pf = _make_plan_mock(), _make_pf_mock()
        p_pf, p_reb, p_plan = _patched(plan, pf)
        with (
            p_pf,
            p_reb,
            p_plan as plan_cls,
            patch("okama_mcp.tools.finplan.ok.FinPlanStage") as stage_cls,
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
            patch("okama_mcp.tools.monte_carlo.ok.PercentageStrategy", return_value=MagicMock()),
        ):
            fp_tool.finplan_forecast(plan=VALID_PLAN)

        assert stage_cls.call_count == 2
        first = stage_cls.call_args_list[0].kwargs
        second = stage_cls.call_args_list[1].kwargs
        assert first["period"] == 20
        assert first["name"] == "accumulation"
        assert first["distribution"] == "norm"
        assert first["distribution_parameters"] is None
        assert second["period"] == 25
        assert second["distribution"] == "t"
        assert second["distribution_parameters"] == (5.0, None, None)

        plan_kwargs = plan_cls.call_args.kwargs
        assert plan_kwargs["initial_investment"] == 100_000.0
        assert plan_kwargs["mc_number"] == 4
        assert plan_kwargs["seed"] == 7
        assert plan_kwargs["name"] == "retirement plan"
        assert len(plan_kwargs["stages"]) == 2

    def test_cashflow_strategy_is_built_on_the_stage_portfolio(self) -> None:
        """okama.FinPlanStage rejects a strategy whose parent is another portfolio."""
        plan, pf = _make_plan_mock(), _make_pf_mock()
        p_pf, p_reb, p_plan = _patched(plan, pf)
        with (
            p_pf,
            p_reb,
            p_plan,
            patch("okama_mcp.tools.finplan.ok.FinPlanStage") as stage_cls,
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()) as ind_cls,
            patch("okama_mcp.tools.monte_carlo.ok.PercentageStrategy", return_value=MagicMock()),
        ):
            fp_tool.finplan_forecast(plan=VALID_PLAN)

        ind_cls.assert_called_once_with(pf)
        first = stage_cls.call_args_list[0].kwargs
        assert first["portfolio"] is pf
        assert first["cashflow_parameters"] is ind_cls.return_value

    def test_stage_without_cashflow_passes_none(self) -> None:
        plan, pf = _make_plan_mock(), _make_pf_mock()
        spec = {"stages": [{"portfolio": {"assets": ["SPY.US"]}, "period_years": 10}], "scenarios": 4}
        p_pf, p_reb, p_plan = _patched(plan, pf)
        with p_pf, p_reb, p_plan, patch("okama_mcp.tools.finplan.ok.FinPlanStage") as stage_cls:
            fp_tool.finplan_forecast(plan=spec)

        assert stage_cls.call_args_list[0].kwargs["cashflow_parameters"] is None

    def test_invalid_spec_raises_okama_mcp_error(self) -> None:
        with pytest.raises(OkamaMcpError):
            fp_tool.finplan_forecast(plan={"stages": []})

    def test_plan_is_cached_across_calls(self) -> None:
        plan, pf = _make_plan_mock(), _make_pf_mock()
        p_pf, p_reb, p_plan = _patched(plan, pf)
        with (
            p_pf,
            p_reb,
            p_plan as plan_cls,
            patch("okama_mcp.tools.finplan.ok.FinPlanStage"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
            patch("okama_mcp.tools.monte_carlo.ok.PercentageStrategy", return_value=MagicMock()),
        ):
            fp_tool.finplan_forecast(plan=VALID_PLAN)
            fp_tool.finplan_forecast(plan=VALID_PLAN)

        assert plan_cls.call_count == 1


class TestForecastPayload:
    def _run(self, **kwargs) -> dict:
        plan, pf = _make_plan_mock(), _make_pf_mock()
        p_pf, p_reb, p_plan = _patched(plan, pf)
        with (
            p_pf,
            p_reb,
            p_plan,
            patch("okama_mcp.tools.finplan.ok.FinPlanStage"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
            patch("okama_mcp.tools.monte_carlo.ok.PercentageStrategy", return_value=MagicMock()),
        ):
            out = fp_tool.finplan_forecast(plan=VALID_PLAN, **kwargs)
        self.plan = plan
        return out

    def test_reports_requested_percentile_bands(self) -> None:
        out = self._run()
        assert set(out["wealth_paths"]["percentiles"].keys()) == {"10", "50", "90"}
        assert out["wealth_paths"]["n_scenarios"] == 4
        assert out["wealth_paths"]["n_months"] == 24
        assert out["wealth_paths"]["index"][0] == "2025-01-31"

    def test_keeps_depleted_scenarios_in_the_statistics(self) -> None:
        self._run()
        # Survival and terminal statistics need the raw paths: zeroing a scenario
        # after it goes broke would hide exactly what those numbers measure.
        # The chart asks for include_negative_values=False on the same cached plan,
        # which okama applies after its simulation cache, so the two never collide.
        self.plan.monte_carlo_wealth.assert_called_once_with(discounting="fv", include_negative_values=True)

    def test_reports_terminal_survival_and_irr(self) -> None:
        out = self._run()
        assert out["terminal_wealth"]["count"] == 4
        assert 0 <= out["survival"]["scenarios_above_zero_pct"] <= 100
        assert set(out["irr"]["percentiles"].keys()) == {"10", "50", "90"}
        assert "mean" in out["irr"]

    def test_reports_probability_of_success_as_percent(self) -> None:
        out = self._run()
        assert out["success"]["probability_pct"] == 75.0
        assert out["success"]["threshold"] == 0.0
        self.plan.probability_of_success.assert_called_once_with(threshold=0.0)

    def test_success_threshold_is_forwarded(self) -> None:
        out = self._run(success_threshold=50_000.0)
        self.plan.probability_of_success.assert_called_once_with(threshold=50_000.0)
        assert out["success"]["threshold"] == 50_000.0

    def test_reports_balance_at_every_stage_boundary(self) -> None:
        out = self._run()
        self.plan.balance_percentiles.assert_called_once_with(percentiles=(10, 50, 90), discounting="fv")
        boundaries = out["stage_boundaries"]
        assert boundaries["index"] == ["accumulation", "retirement"]
        assert boundaries["columns"] == ["10%", "50%", "90%"]

    def test_echoes_stage_summary(self) -> None:
        out = self._run()
        assert [s["name"] for s in out["stages"]] == ["accumulation", "retirement"]
        assert [s["period_years"] for s in out["stages"]] == [20, 25]
        assert [s["distribution"] for s in out["stages"]] == ["norm", "t"]
        assert out["total_period_years"] == 45


class TestBacktest:
    def _run(self, **kwargs) -> tuple[dict, SimpleNamespace]:
        plan, pf = _make_plan_mock(), _make_pf_mock()
        p_pf, p_reb, p_plan = _patched(plan, pf)
        with (
            p_pf,
            p_reb,
            p_plan,
            patch("okama_mcp.tools.finplan.ok.FinPlanStage"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
            patch("okama_mcp.tools.monte_carlo.ok.PercentageStrategy", return_value=MagicMock()),
        ):
            out = fp_tool.finplan_backtest(plan=VALID_PLAN, **kwargs)
        return out, plan

    def test_returns_wealth_index_and_cash_flow(self) -> None:
        out, plan = self._run()
        assert out["wealth_index"]["columns"] == ["plan", "RUB.INFL"]
        assert out["cash_flow"]["name"] == "cash_flow"
        assert out["discounting"] == "fv"

    def test_forwards_discounting_and_first_date(self) -> None:
        _, plan = self._run(discounting="pv", first_date="2005-01")
        plan.wealth_index.assert_called_once_with(discounting="pv", first_date="2005-01")
        plan.cash_flow_ts.assert_called_once_with(discounting="pv", first_date="2005-01")

    def test_rejects_unknown_discounting(self) -> None:
        with pytest.raises(OkamaMcpError):
            self._run(discounting="real")
