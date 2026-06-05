"""Tests for okama_mcp.schemas — pydantic input contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from okama_mcp.schemas import (
    CashflowAdapter,
    CutIfDrawdownCashflow,
    IndexationCashflow,
    MCSpec,
    PercentageCashflow,
    PortfolioSpec,
    TimeSeriesCashflow,
    VanguardDynamicCashflow,
)


class TestPortfolioSpec:
    def test_minimal_valid(self) -> None:
        spec = PortfolioSpec(assets=["SPY.US", "GLD.US"])
        assert spec.assets == ["SPY.US", "GLD.US"]
        assert spec.ccy == "USD"
        assert spec.rebalancing_strategy.period == "year"
        assert spec.rebalancing_strategy.abs_deviation is None
        assert spec.rebalancing_strategy.rel_deviation is None
        assert spec.inflation is True
        assert spec.weights is None

    def test_empty_assets_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=[])

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A", "B"], weights=[0.5, 0.3])

    def test_weights_sum_within_tolerance_ok(self) -> None:
        # Within 1e-6 tolerance
        PortfolioSpec(assets=["A", "B"], weights=[0.5000001, 0.5])

    def test_weights_length_must_match_assets(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A", "B"], weights=[1.0])

    def test_weights_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A", "B"], weights=[1.2, -0.2])

    def test_invalid_rebalancing_period(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A"], rebalancing_strategy={"period": "weekly"})

    def test_legacy_rebalancing_period_field_rejected(self) -> None:
        # The old flat field was replaced by rebalancing_strategy; extra="forbid"
        # must reject it so the LLM gets a clear validation error.
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A"], rebalancing_period="year")

    def test_rebalancing_strategy_with_deviations(self) -> None:
        spec = PortfolioSpec(
            assets=["A"],
            rebalancing_strategy={
                "period": "quarter",
                "abs_deviation": 0.05,
                "rel_deviation": 0.1,
            },
        )
        assert spec.rebalancing_strategy.period == "quarter"
        assert spec.rebalancing_strategy.abs_deviation == 0.05
        assert spec.rebalancing_strategy.rel_deviation == 0.1

    def test_abs_deviation_must_be_in_zero_one(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A"], rebalancing_strategy={"abs_deviation": 0.0})
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A"], rebalancing_strategy={"abs_deviation": 1.5})
        PortfolioSpec(assets=["A"], rebalancing_strategy={"abs_deviation": 1.0})

    def test_rel_deviation_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A"], rebalancing_strategy={"rel_deviation": 0.0})
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=["A"], rebalancing_strategy={"rel_deviation": -0.1})

    def test_full_spec(self) -> None:
        spec = PortfolioSpec(
            assets=["GLD.US", "VNQ.US"],
            weights=[0.3, 0.7],
            ccy="USD",
            first_date="2010-01",
            last_date="2024-12",
            rebalancing_strategy={"period": "year"},
            inflation=True,
            symbol="gold_re.PF",
        )
        assert spec.weights == [0.3, 0.7]
        assert spec.first_date == "2010-01"


class TestMCSpec:
    def test_defaults(self) -> None:
        mc = MCSpec()
        assert mc.distribution == "norm"
        assert mc.period_years == 25
        assert mc.scenarios == 500

    def test_scenarios_cap(self) -> None:
        with pytest.raises(ValidationError):
            MCSpec(scenarios=10_000)

    def test_period_years_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            MCSpec(period_years=0)

    def test_invalid_distribution(self) -> None:
        with pytest.raises(ValidationError):
            MCSpec(distribution="cauchy")

    def test_percentiles_in_range(self) -> None:
        MCSpec(percentiles=[5, 50, 95])
        with pytest.raises(ValidationError):
            MCSpec(percentiles=[5, 110])


class TestCashflowSpec:
    def test_indexation_cashflow(self) -> None:
        cf = IndexationCashflow(
            initial_investment=1_000_000,
            frequency="month",
            amount=-1000,
            indexation="inflation",
        )
        assert cf.type == "indexation"

    def test_indexation_initial_investment_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            IndexationCashflow(
                initial_investment=-1.0, frequency="month", amount=-1000
            )

    def test_percentage_cashflow(self) -> None:
        cf = PercentageCashflow(
            initial_investment=1_000_000,
            frequency="year",
            percentage=-0.04,
        )
        assert cf.type == "percentage"

    def test_percentage_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PercentageCashflow(
                initial_investment=1.0, frequency="year", percentage=-2.0
            )

    def test_time_series_cashflow(self) -> None:
        cf = TimeSeriesCashflow(
            initial_investment=1000,
            events={"2025-06": -50_000, "2030-01": 10_000},
        )
        assert cf.type == "time_series"

    def test_vanguard_cashflow(self) -> None:
        cf = VanguardDynamicCashflow(
            initial_investment=1_000_000,
            percentage=-0.04,
            floor_ceiling=[-0.025, 0.05],
            indexation="inflation",
        )
        assert cf.type == "vanguard"

    def test_cut_if_drawdown_cashflow(self) -> None:
        cf = CutIfDrawdownCashflow(
            initial_investment=1_000_000,
            frequency="year",
            amount=-60_000,
            indexation="inflation",
            crash_threshold_reduction=[[0.20, 0.40], [0.50, 1.0]],
        )
        assert cf.type == "cut_if_drawdown"


class TestCashflowDiscriminator:
    def test_indexation_dispatched_by_type(self) -> None:
        cf = CashflowAdapter.validate_python(
            {
                "type": "indexation",
                "initial_investment": 1_000_000,
                "frequency": "month",
                "amount": -1000,
                "indexation": "inflation",
            }
        )
        assert isinstance(cf, IndexationCashflow)

    def test_percentage_dispatched_by_type(self) -> None:
        cf = CashflowAdapter.validate_python(
            {
                "type": "percentage",
                "initial_investment": 1_000_000,
                "frequency": "year",
                "percentage": -0.04,
            }
        )
        assert isinstance(cf, PercentageCashflow)

    def test_missing_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CashflowAdapter.validate_python(
                {"initial_investment": 1, "frequency": "month", "amount": -1}
            )

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CashflowAdapter.validate_python(
                {"type": "lottery", "initial_investment": 1}
            )
