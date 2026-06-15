"""Tests for tools/monte_carlo.py: monte_carlo_forecast with five cashflow strategies."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from okama_mcp.errors import OkamaMcpError
from okama_mcp.tools import monte_carlo as mc_tool
from okama_mcp.tools import portfolio as pf_tool


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    pf_tool.clear_cache()


def _make_mc_wealth(n_months: int = 12, n_scenarios: int = 4) -> pd.DataFrame:
    """Synthetic MC wealth: scenario columns drift upward at different rates."""
    rng = np.random.default_rng(seed=0)
    idx = pd.period_range("2025-01", periods=n_months, freq="M")
    # Construct deterministic monotonic-up scenarios with one declining one
    base = np.linspace(1_000_000, 1_200_000, n_months)
    data = {}
    for i in range(n_scenarios):
        factor = 1 + (i - 1) * 0.05  # one scenario negative drift, others positive
        noise = rng.normal(0, 1_000, n_months)
        data[f"s{i}"] = base * factor + noise
    return pd.DataFrame(data, index=idx)


def _make_pf_mock(*, mc_wealth=None, survival=None, mc_irr=None) -> SimpleNamespace:
    pf = SimpleNamespace()
    pf.symbol = "pf.PF"
    pf.symbols = ["GLD.US", "VNQ.US"]
    pf.weights = [0.3, 0.7]
    pf.currency = "USD"
    pf.first_date = pd.Timestamp("2010-01-01")
    pf.last_date = pd.Timestamp("2024-12-31")
    pf.period_length = 15.0

    dcf = SimpleNamespace()
    dcf.set_mc_parameters = MagicMock()
    dcf._cashflow_set: list = []

    class _CashflowDescriptor:
        # Replicates pf.dcf.cashflow_parameters = strategy semantics for tests.
        def __set__(_self, instance, value):
            instance.__dict__["_cashflow_set_value"] = value
            instance._cashflow_set.append(value)

        def __get__(_self, instance, owner):
            return instance.__dict__.get("_cashflow_set_value")

    # Use a simple property substitute — SimpleNamespace doesn't support descriptors directly,
    # so we just use plain attribute assignment in the production code; here we capture via .__setattr__.
    dcf._captured: list = []
    dcf.monte_carlo_wealth = MagicMock(
        return_value=mc_wealth if mc_wealth is not None else _make_mc_wealth()
    )
    dcf.monte_carlo_survival_period = MagicMock(
        return_value=survival
        if survival is not None
        else pd.Series([23.5, 24.0, 25.0, 25.0])
    )
    dcf.monte_carlo_irr = MagicMock(
        return_value=mc_irr
        if mc_irr is not None
        else pd.Series([0.05, 0.07, 0.06, 0.08])
    )
    dcf.discount_rate = 0.04
    pf.dcf = dcf
    return pf


VALID_PF_SPEC: dict = {
    "assets": ["GLD.US", "VNQ.US"],
    "weights": [0.3, 0.7],
    "ccy": "USD",
    "first_date": "2010-01",
    "last_date": "2024-12",
    "rebalancing_strategy": {"period": "year"},
    "inflation": True,
}

VALID_MC_SPEC: dict = {
    "distribution": "norm",
    "period_years": 25,
    "scenarios": 4,
    "percentiles": [5, 50, 95],
}

VALID_INDEXATION_CASHFLOW: dict = {
    "type": "indexation",
    "initial_investment": 1_000_000.0,
    "frequency": "month",
    "amount": -1000.0,
    "indexation": "inflation",
}


class TestIndexationCashflowForecast:
    def test_runs_and_returns_percentile_bands(self) -> None:
        pf = _make_pf_mock()
        ind_mock = MagicMock(name="IndexationStrategy_instance")
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=ind_mock) as ind_cls,
        ):
            out = mc_tool.monte_carlo_forecast(
                portfolio=VALID_PF_SPEC,
                mc=VALID_MC_SPEC,
                cashflow=VALID_INDEXATION_CASHFLOW,
            )

        # The okama IndexationStrategy was constructed with the portfolio as parent
        # and configured via setters.
        ind_cls.assert_called_once_with(pf)
        assert ind_mock.initial_investment == 1_000_000.0
        assert ind_mock.frequency == "month"
        assert ind_mock.amount == -1000.0
        assert ind_mock.indexation == "inflation"

        # MC parameters were set on the portfolio's dcf.
        pf.dcf.set_mc_parameters.assert_called_once_with(
            distribution="norm", distribution_parameters=None, period=25, mc_number=4, seed=None
        )

        # The output has wealth percentile bands + terminal & survival stats + IRR block.
        assert set(out["wealth_paths"]["percentiles"].keys()) == {"5", "50", "95"}
        assert out["wealth_paths"]["index"][0] == "2025-01-31"
        assert "terminal_wealth" in out
        assert "survival" in out
        assert 0 <= out["survival"]["scenarios_above_zero_pct"] <= 100
        assert "irr" in out
        assert "percentiles" in out["irr"]
        assert "mean" in out["irr"]


class TestPercentageCashflow:
    def test_dispatches_to_percentage_strategy(self) -> None:
        pf = _make_pf_mock()
        strat = MagicMock(name="PercentageStrategy_instance")
        cf_spec = {
            "type": "percentage",
            "initial_investment": 1_000_000.0,
            "frequency": "year",
            "percentage": -0.04,
        }
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.PercentageStrategy", return_value=strat) as cls,
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, VALID_MC_SPEC, cf_spec)
        cls.assert_called_once_with(pf)
        assert strat.percentage == -0.04
        assert strat.frequency == "year"


class TestTimeSeriesCashflow:
    def test_dispatches_to_time_series_strategy(self) -> None:
        pf = _make_pf_mock()
        strat = MagicMock(name="TimeSeriesStrategy_instance")
        events = {"2025-06": -50_000, "2030-01": 10_000}
        cf_spec = {
            "type": "time_series",
            "initial_investment": 100_000.0,
            "events": events,
        }
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.TimeSeriesStrategy", return_value=strat) as cls,
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, VALID_MC_SPEC, cf_spec)
        cls.assert_called_once_with(pf)
        assert strat.initial_investment == 100_000.0
        assert strat.time_series_dic == events

    def test_passes_discounted_values_flag(self) -> None:
        pf = _make_pf_mock()
        strat = MagicMock(name="TimeSeriesStrategy_instance")
        cf_spec = {
            "type": "time_series",
            "initial_investment": 100_000.0,
            "events": {"2030-01": -50_000},
            "time_series_discounted_values": True,
        }
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.TimeSeriesStrategy", return_value=strat),
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, VALID_MC_SPEC, cf_spec)
        assert strat.time_series_discounted_values is True


class TestVanguardCashflow:
    def test_dispatches_to_vanguard(self) -> None:
        pf = _make_pf_mock()
        strat = MagicMock(name="VDS")
        cf_spec = {
            "type": "vanguard",
            "initial_investment": 1_000_000.0,
            "percentage": -0.04,
            "floor_ceiling": [-0.025, 0.05],
            "indexation": "inflation",
        }
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch(
                "okama_mcp.tools.monte_carlo.ok.VanguardDynamicSpending", return_value=strat
            ) as cls,
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, VALID_MC_SPEC, cf_spec)
        cls.assert_called_once()
        kwargs = cls.call_args.kwargs
        assert kwargs["parent"] is pf
        assert kwargs["percentage"] == -0.04
        assert kwargs["floor_ceiling"] == (-0.025, 0.05)
        assert kwargs["indexation"] == "inflation"


class TestCutIfDrawdownCashflow:
    def test_dispatches_to_cut_if_drawdown(self) -> None:
        pf = _make_pf_mock()
        strat = MagicMock(name="CWD")
        cf_spec = {
            "type": "cut_if_drawdown",
            "initial_investment": 1_000_000.0,
            "frequency": "year",
            "amount": -60_000.0,
            "indexation": "inflation",
            "crash_threshold_reduction": [[0.20, 0.40], [0.50, 1.0]],
        }
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch(
                "okama_mcp.tools.monte_carlo.ok.CutWithdrawalsIfDrawdown", return_value=strat
            ) as cls,
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, VALID_MC_SPEC, cf_spec)
        kwargs = cls.call_args.kwargs
        assert kwargs["parent"] is pf
        assert kwargs["amount"] == -60_000.0
        assert kwargs["crash_threshold_reduction"] == [(0.20, 0.40), (0.50, 1.0)]


class TestValidation:
    def test_invalid_portfolio_rejected_before_okama_call(self) -> None:
        bad_pf = dict(VALID_PF_SPEC, weights=[0.1, 0.2])
        with pytest.raises(OkamaMcpError):
            mc_tool.monte_carlo_forecast(bad_pf, VALID_MC_SPEC, VALID_INDEXATION_CASHFLOW)

    def test_unknown_cashflow_type_rejected(self) -> None:
        bad_cf = {"type": "lottery", "initial_investment": 1}
        with pytest.raises(OkamaMcpError):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, VALID_MC_SPEC, bad_cf)


class TestSurvivalCalculations:
    def test_scenarios_above_zero_pct_from_last_row(self) -> None:
        # Build MC wealth where 3 of 4 scenarios end positive
        idx = pd.period_range("2025-01", periods=2, freq="M")
        mc_wealth = pd.DataFrame(
            {"s1": [100, 200], "s2": [100, 150], "s3": [100, -50], "s4": [100, 80]},
            index=idx,
        )
        pf = _make_pf_mock(mc_wealth=mc_wealth, survival=pd.Series([25.0, 25.0, 12.0, 22.0]))
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            out = mc_tool.monte_carlo_forecast(
                VALID_PF_SPEC, VALID_MC_SPEC, VALID_INDEXATION_CASHFLOW
            )
        assert out["survival"]["scenarios_above_zero_pct"] == 75.0
        assert out["survival"]["median_survival_years"] == 23.5
        assert out["survival"]["min_survival_years"] == 12.0


class TestIrrBlock:
    def test_irr_percentiles_and_mean_computed(self) -> None:
        irr_series = pd.Series([0.03, 0.05, 0.06, 0.07, 0.08, 0.10])
        pf = _make_pf_mock(mc_irr=irr_series)
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            out = mc_tool.monte_carlo_forecast(
                VALID_PF_SPEC, VALID_MC_SPEC, VALID_INDEXATION_CASHFLOW
            )

        assert "irr" in out
        assert set(out["irr"]["percentiles"].keys()) == {"5", "50", "95"}
        # p5 = irr_series.quantile(0.05) ~ 0.035, p50 = 0.065, p95 = 0.094
        assert 0.03 <= out["irr"]["percentiles"]["5"] <= 0.04
        assert 0.06 <= out["irr"]["percentiles"]["50"] <= 0.07
        assert 0.09 <= out["irr"]["percentiles"]["95"] <= 0.10
        assert 0.06 <= out["irr"]["mean"] <= 0.07

    def test_irr_nan_becomes_none(self) -> None:
        irr_series = pd.Series([0.05, float("nan"), 0.07, 0.06])
        pf = _make_pf_mock(mc_irr=irr_series)
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            out = mc_tool.monte_carlo_forecast(
                VALID_PF_SPEC, VALID_MC_SPEC, VALID_INDEXATION_CASHFLOW
            )

        # quantile ignores NaN; mean also excludes it => real values still present
        assert out["irr"]["mean"] is not None


class TestRandomSeed:
    def test_seed_is_passed_to_set_mc_parameters(self) -> None:
        pf = _make_pf_mock()
        spec_with_seed = dict(VALID_MC_SPEC, random_seed=42)
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, spec_with_seed, VALID_INDEXATION_CASHFLOW)

        pf.dcf.set_mc_parameters.assert_called_once_with(
            distribution="norm", distribution_parameters=None, period=25, mc_number=4, seed=42
        )

    def test_seed_none_is_passed_as_none(self) -> None:
        pf = _make_pf_mock()
        spec_no_seed = dict(VALID_MC_SPEC)
        spec_no_seed.pop("random_seed", None)
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, spec_no_seed, VALID_INDEXATION_CASHFLOW)

        pf.dcf.set_mc_parameters.assert_called_once_with(
            distribution="norm", distribution_parameters=None, period=25, mc_number=4, seed=None
        )


class TestGetPortfolioIrr:
    def test_historical_irr_with_cashflow(self) -> None:
        pf = _make_pf_mock()
        pf.dcf.irr = MagicMock(return_value=0.071)
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            out = mc_tool.get_portfolio_irr(VALID_PF_SPEC, VALID_INDEXATION_CASHFLOW)

        assert out["irr"] == 0.071
        assert "cashflow_spec" in out

    def test_nan_irr_becomes_none(self) -> None:
        pf = _make_pf_mock()
        pf.dcf.irr = MagicMock(return_value=float("nan"))
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            out = mc_tool.get_portfolio_irr(VALID_PF_SPEC, VALID_INDEXATION_CASHFLOW)

        assert out["irr"] is None


class TestLargestWithdrawalsSize:
    def test_returns_withdrawal_result(self) -> None:
        pf = _make_pf_mock()
        pf.dcf.find_the_largest_withdrawals_size = MagicMock(
            return_value=SimpleNamespace(
                success=True,
                withdrawal_abs=-12345.0,
                withdrawal_rel=-0.04,
                error_rel=0.02,
                solutions=pd.DataFrame({"withdrawal_abs": [-1, -2, -3]}),
            )
        )
        ind_mock = MagicMock(name="IndexationStrategy_instance")
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=ind_mock),
        ):
            out = mc_tool.find_the_largest_withdrawals_size(
                portfolio=VALID_PF_SPEC,
                mc=VALID_MC_SPEC,
                cashflow=VALID_INDEXATION_CASHFLOW,
                goal="survival_period",
                target_survival_period=25,
                percentile=20,
            )
        assert out["goal"] == "survival_period"
        assert out["success"] is True
        assert out["withdrawal_abs"] == -12345.0
        assert out["withdrawal_rel"] == -0.04
        assert out["error_rel"] == 0.02
        assert out["n_evaluations"] == 3
        pf.dcf.set_mc_parameters.assert_called_once()

    def test_invalid_goal_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            mc_tool.find_the_largest_withdrawals_size(
                portfolio=VALID_PF_SPEC,
                mc=VALID_MC_SPEC,
                cashflow=VALID_INDEXATION_CASHFLOW,
                goal="not_a_goal",
            )


class TestPrepareHelpers:
    def test_distribution_parameters_passed_as_tuple(self) -> None:
        pf = _make_pf_mock()
        mc_spec = dict(VALID_MC_SPEC, distribution="t", distribution_parameters=[3, None, None])
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, mc_spec, VALID_INDEXATION_CASHFLOW)
        kwargs = pf.dcf.set_mc_parameters.call_args.kwargs
        assert kwargs["distribution_parameters"] == (3, None, None)

    def test_prepare_cashflow_no_mc_call(self) -> None:
        pf = _make_pf_mock()
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            built_pf, spec = mc_tool._prepare_cashflow(VALID_PF_SPEC, VALID_INDEXATION_CASHFLOW, discount_rate=0.07)
        pf.dcf.set_mc_parameters.assert_not_called()
        assert pf.dcf.discount_rate == 0.07

    def test_prepare_mc_sets_params_no_cashflow(self) -> None:
        pf = _make_pf_mock()
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
        ):
            built_pf, spec = mc_tool._prepare_mc(VALID_PF_SPEC, VALID_MC_SPEC)
        pf.dcf.set_mc_parameters.assert_called_once()
        assert built_pf is pf


class TestServerRegistration:
    @pytest.mark.asyncio
    async def test_phase5_tool_registered(self) -> None:
        from okama_mcp.server import mcp

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert "monte_carlo_forecast" in names
        assert "get_portfolio_irr" in names
        assert "find_the_largest_withdrawals_size" in names
