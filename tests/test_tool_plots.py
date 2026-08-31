"""Tests for tools/plots.py: PNG chart tools."""

import struct
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastmcp.utilities.types import Image

import okama_mcp.tools.plots as plots_tool
import okama_mcp.tools.portfolio as pf_tool
import okama_mcp.tools.frontier as fr_tool
import okama_mcp.tools.finplan as fp_tool
from okama_mcp.errors import OkamaMcpError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

VALID_SPEC: dict = {
    "assets": ["GLD.US", "VNQ.US"],
    "weights": [0.3, 0.7],
    "ccy": "USD",
    "first_date": "2010-01",
    "last_date": "2024-12",
    "rebalancing_strategy": {"period": "year"},
    "inflation": True,
}


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    pf_tool.clear_cache()
    fr_tool.clear_cache()
    fp_tool.clear_cache()


def _make_portfolio_mock() -> SimpleNamespace:
    idx = pd.period_range("2010-01", periods=6, freq="M")
    pf = SimpleNamespace()
    pf.symbol = "pf.PF"
    pf.currency = "USD"
    pf.wealth_index = pd.DataFrame(
        {
            "pf.PF": [1000.0, 1010.0, 1020.0, 1015.0, 1030.0, 1050.0],
            "USD.INFL": [1000.0, 1002.0, 1004.5, 1006.0, 1008.2, 1010.1],
        },
        index=idx,
    )
    pf.drawdowns = pd.Series([0.0, 0.0, 0.0, -0.005, 0.0, 0.0], index=idx, name="dd")
    return pf


class TestPlotWealthIndex:
    def test_returns_png_image(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_wealth_index(VALID_SPEC)

        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)
        assert struct.unpack(">II", out.data[16:24]) == (1500, 900)

    def test_invalid_spec_raises_actionable_error(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_wealth_index({"assets": []})

    def test_custom_size_and_aspect_ratio(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_wealth_index(VALID_SPEC, width=800, height=800)

        assert struct.unpack(">II", out.data[16:24]) == (800, 800)

    def test_out_of_bounds_size_rejected(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            with pytest.raises(OkamaMcpError):
                plots_tool.plot_wealth_index(VALID_SPEC, width=50, height=50)


class TestPlotDrawdowns:
    def test_returns_png_image(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_drawdowns(VALID_SPEC)

        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)


FRONTIER_SPEC: dict = {
    "assets": ["SPY.US", "BND.US"],
    "ccy": "USD",
    "n_points": 4,
    "rebalancing_strategy": {"period": "year"},
    "inflation": False,
}


def _make_frontier_mock() -> SimpleNamespace:
    ef = SimpleNamespace()
    ef.symbols = ["SPY.US", "BND.US"]
    ef.ef_points = pd.DataFrame(
        {
            "Risk": [0.05, 0.08, 0.12, 0.18],
            "Mean return": [0.04, 0.07, 0.09, 0.11],
            "CAGR": [0.038, 0.067, 0.085, 0.105],
            "SPY.US": [0.0, 0.4, 0.7, 1.0],
            "BND.US": [1.0, 0.6, 0.3, 0.0],
        }
    )
    ef.risk_annual = pd.Series({"SPY.US": 0.17, "BND.US": 0.05})
    # mean_return may carry an inflation entry — the tool must filter to symbols.
    ef.mean_return = pd.Series({"SPY.US": 0.10, "BND.US": 0.04, "USD.INFL": 0.025})
    return ef


class TestPlotEfficientFrontier:
    def test_returns_png_image(self) -> None:
        ef = _make_frontier_mock()
        with patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef):
            out = plots_tool.plot_efficient_frontier(FRONTIER_SPEC)

        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)


MC_SPEC: dict = {"distribution": "norm", "period_years": 2, "scenarios": 20,
                 "percentiles": [10, 50, 90], "random_seed": 42}
CASHFLOW_SPEC: dict = {"type": "indexation", "initial_investment": 100000,
                       "frequency": "year", "amount": -4000, "indexation": "inflation"}


def _make_mc_portfolio_mock() -> SimpleNamespace:
    pf = _make_portfolio_mock()
    n_periods, n_scenarios = 24, 20
    idx = pd.period_range("2025-01", periods=n_periods, freq="M")
    rng_matrix = {
        f"s{i}": [100000.0 * (1 + 0.001 * i + 0.002 * t) for t in range(n_periods)]
        for i in range(n_scenarios)
    }
    mc_wealth = pd.DataFrame(rng_matrix, index=idx)
    pf.dcf = SimpleNamespace(
        set_mc_parameters=lambda **kw: None,
        monte_carlo_wealth=lambda **kw: mc_wealth,
        monte_carlo_irr=lambda: pd.Series([0.02, 0.05, 0.071, 0.08, 0.11] * 4),
    )
    return pf


class TestPlotMonteCarlo:
    def test_returns_png_image(self) -> None:
        pf = _make_mc_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"), \
             patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy",
                   return_value=SimpleNamespace()):
            out = plots_tool.plot_monte_carlo(VALID_SPEC, MC_SPEC, CASHFLOW_SPEC)

        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)


class TestPlotIrrDistribution:
    def test_returns_png_image(self) -> None:
        pf = _make_mc_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"), \
             patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy",
                   return_value=SimpleNamespace()):
            out = plots_tool.plot_irr_distribution(VALID_SPEC, MC_SPEC, CASHFLOW_SPEC)

        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)


class TestPlotAssets:
    def test_returns_png_image(self) -> None:
        idx = pd.period_range("2020-01", periods=6, freq="M")
        al = SimpleNamespace()
        al.wealth_indexes = pd.DataFrame(
            {"SPY.US": [1000, 1020, 1040, 1030, 1060, 1100],
             "GLD.US": [1000, 990, 1010, 1030, 1020, 1050]},
            index=idx, dtype=float,
        )
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=al):
            out = plots_tool.plot_assets(["SPY.US", "GLD.US"], "USD")

        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)

    def test_empty_symbols_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_assets([], "USD")


class TestSavePath:
    def test_save_path_writes_png_and_reports_path(self, tmp_path) -> None:
        pf = _make_portfolio_mock()
        target = tmp_path / "charts" / "wealth.png"  # parent dir doesn't exist yet
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_wealth_index(VALID_SPEC, save_path=str(target))

        assert isinstance(out, list) and len(out) == 2
        image, message = out
        assert isinstance(image, Image)
        assert image.data.startswith(PNG_MAGIC)
        assert str(target) in message
        assert target.read_bytes().startswith(PNG_MAGIC)
        assert target.read_bytes() == image.data

    def test_without_save_path_returns_bare_image(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_wealth_index(VALID_SPEC)

        assert isinstance(out, Image)

    @pytest.mark.asyncio
    async def test_save_path_yields_image_and_text_blocks_over_mcp(self, tmp_path) -> None:
        """Lock the FastMCP conversion contract: [Image, str] -> image + text blocks."""
        from fastmcp import Client

        from okama_mcp.server import mcp

        pf = _make_portfolio_mock()
        target = tmp_path / "wealth.png"
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "plot_wealth_index",
                    {"portfolio": VALID_SPEC, "save_path": str(target)},
                )

        assert [c.type for c in result.content] == ["image", "text"]
        assert str(target) in result.content[1].text
        assert target.read_bytes().startswith(PNG_MAGIC)


def _make_macro_series_mock(symbol: str) -> SimpleNamespace:
    idx = pd.period_range("2020-01", periods=6, freq="M")
    monthly = pd.Series([30.0, 31.0, 29.5, 32.0, 33.0, 31.5], index=idx, name=symbol)
    didx = pd.date_range("2024-01-01", periods=6, freq="D")
    daily_s = pd.Series([0.05, 0.05, 0.049, 0.049, 0.048, 0.048], index=didx, name=symbol)
    return SimpleNamespace(symbol=symbol, values_monthly=monthly, values_daily=daily_s)


class TestPlotMacro:
    def test_returns_png_for_cape10(self) -> None:
        ind = _make_macro_series_mock("USA_CAPE10.RATIO")
        with patch("okama_mcp.tools.plots.ok.Indicator", return_value=ind):
            out = plots_tool.plot_macro(["USA_CAPE10.RATIO"])
        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)
        assert struct.unpack(">II", out.data[16:24]) == (1500, 900)

    def test_multiple_symbols_overlay(self) -> None:
        usa = _make_macro_series_mock("USA_CAPE10.RATIO")
        eur = _make_macro_series_mock("EUR_CAPE10.RATIO")
        with patch("okama_mcp.tools.plots.ok.Indicator", side_effect=[usa, eur]):
            out = plots_tool.plot_macro(["USA", "EUR"])
        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)

    def test_daily_frequency_on_rate(self) -> None:
        rate = _make_macro_series_mock("US_EFFR.RATE")
        with patch("okama_mcp.tools.plots.ok.Rate", return_value=rate):
            out = plots_tool.plot_macro(["US_EFFR.RATE"], frequency="daily")
        assert isinstance(out, Image)

    def test_daily_on_non_rate_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_macro(["USA_CAPE10.RATIO"], frequency="daily")

    def test_empty_symbols_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_macro([])

    def test_invalid_frequency_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_macro(["USA_CAPE10.RATIO"], frequency="weekly")

    def test_save_path_writes_png(self, tmp_path) -> None:
        ind = _make_macro_series_mock("USA_CAPE10.RATIO")
        target = tmp_path / "cape.png"
        with patch("okama_mcp.tools.plots.ok.Indicator", return_value=ind):
            out = plots_tool.plot_macro(["USA_CAPE10.RATIO"], save_path=str(target))
        assert isinstance(out, list) and len(out) == 2
        assert target.read_bytes().startswith(PNG_MAGIC)


def _make_ef_mock_for_tm() -> SimpleNamespace:
    ef = SimpleNamespace()
    ef.symbols = ["SPY.US", "GLD.US", "BND.US"]
    ef.currency = "USD"
    ef.ef_points = pd.DataFrame(
        {
            "Risk": [0.05, 0.08, 0.12, 0.18],
            "Mean return": [0.04, 0.07, 0.09, 0.11],
            "CAGR": [0.038, 0.067, 0.085, 0.105],
            "SPY.US": [0.10, 0.30, 0.60, 1.00],
            "GLD.US": [0.20, 0.30, 0.30, 0.00],
            "BND.US": [0.70, 0.40, 0.10, 0.00],
        }
    )
    return ef


VALID_FRONTIER_SPEC: dict = {
    "assets": ["SPY.US", "GLD.US", "BND.US"],
    "ccy": "USD",
    "n_points": 4,
}


class TestPlotTransitionMap:
    def test_returns_png_image(self) -> None:
        ef = _make_ef_mock_for_tm()
        with patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef), \
             patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_transition_map(VALID_FRONTIER_SPEC)
        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)

    def test_invalid_x_axe_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_transition_map(VALID_FRONTIER_SPEC, x_axe="time")


class TestServerRegistration:
    @pytest.mark.asyncio
    async def test_plot_tools_registered(self) -> None:
        from okama_mcp.server import mcp

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        for tool in ("plot_wealth_index", "plot_drawdowns", "plot_efficient_frontier",
                     "plot_monte_carlo", "plot_assets", "plot_irr_distribution",
                     "plot_transition_map", "plot_qq", "plot_hist_fit", "plot_macro"):
            assert tool in names


MC_SPEC_T: dict = {"distribution": "t", "period_years": 10, "scenarios": 50}


def _pf_with_ror() -> SimpleNamespace:
    pf = SimpleNamespace()
    pf.symbol = "pf.PF"
    pf.symbols = ["GLD.US"]
    dcf = SimpleNamespace()
    dcf.set_mc_parameters = lambda **kwargs: None
    rng = np.random.default_rng(0)
    mc = SimpleNamespace()
    mc.ror = pd.Series(rng.normal(0.005, 0.04, 120))
    mc.get_parameters_for_distribution = lambda: (5.0, 0.005, 0.04)
    dcf.mc = mc
    pf.dcf = dcf
    return pf


class TestPlotQQ:
    def test_returns_image(self) -> None:
        pf = _pf_with_ror()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_qq(VALID_SPEC, MC_SPEC_T)
        assert isinstance(out, Image)


class TestPlotHistFit:
    def test_returns_image(self) -> None:
        pf = _pf_with_ror()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_hist_fit(VALID_SPEC, MC_SPEC_T)
        assert isinstance(out, Image)


FINPLAN_SPEC: dict = {
    "stages": [
        {
            "portfolio": VALID_SPEC,
            "period_years": 20,
            "name": "accumulation",
            "cashflow": {
                "type": "indexation",
                "initial_investment": 100_000.0,
                "frequency": "year",
                "amount": 12_000.0,
            },
        },
        {"portfolio": VALID_SPEC, "period_years": 25, "name": "retirement"},
    ],
    "initial_investment": 100_000.0,
    "scenarios": 4,
    "percentiles": [10, 50, 90],
}


def _make_finplan_mock() -> SimpleNamespace:
    # Two 12-month stages. Like okama, the frame opens with the starting balance
    # dated one month before t0, so it has 25 rows and row 13 is the first month
    # of the second stage.
    idx = pd.period_range("2024-12", periods=25, freq="M")
    base = np.linspace(100_000, 250_000, 25)
    wealth = pd.DataFrame({f"s{i}": base * (1 + (i - 1) * 0.1) for i in range(4)}, index=idx)
    plan = SimpleNamespace()
    plan.name = "plan"
    # okama.FinPlan has no `currency` of its own: it validates that every stage
    # portfolio shares one currency and leaves the value on the portfolios.
    plan.monte_carlo_wealth = MagicMock(return_value=wealth)
    plan.stages = [
        SimpleNamespace(name="accumulation", period_months=12, portfolio=SimpleNamespace(currency="USD")),
        SimpleNamespace(name="retirement", period_months=12, portfolio=SimpleNamespace(currency="USD")),
    ]

    def _must_not_be_called(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("plot_forecast_monte_carlo goes through pyplot and is not thread-safe")

    plan.plot_forecast_monte_carlo = _must_not_be_called
    return plan


class TestPlotFinPlanForecast:
    def _run(self, **kwargs):
        plan = _make_finplan_mock()
        captured: dict = {}
        real_make_figure = plots_tool.make_figure

        def _spy(width_px: int, height_px: int):
            fig, ax = real_make_figure(width_px, height_px)
            captured["ax"] = ax
            return fig, ax

        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=_make_portfolio_mock()), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"), \
             patch("okama_mcp.tools.finplan.ok.FinPlanStage"), \
             patch("okama_mcp.tools.finplan.ok.FinPlan", return_value=plan), \
             patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=SimpleNamespace()), \
             patch.object(plots_tool, "make_figure", _spy):
            out = plots_tool.plot_finplan_forecast(FINPLAN_SPEC, **kwargs)
        self.plan = plan
        return out, captured["ax"]

    def test_returns_png_image(self) -> None:
        out, _ = self._run()
        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)

    def test_draws_one_line_per_requested_percentile(self) -> None:
        _, ax = self._run()
        labels = [line.get_label() for line in ax.get_lines()]
        assert [label for label in labels if str(label).startswith("p")] == ["p10", "p50", "p90"]

    def test_marks_every_stage_boundary_but_not_the_plan_end(self) -> None:
        _, ax = self._run()
        # Two stages -> exactly one internal boundary, drawn as a dashed vertical line.
        dashed = [line for line in ax.get_lines() if line.get_linestyle() == "--"]
        assert len(dashed) == 1

    def test_boundary_sits_on_the_first_month_of_the_next_stage(self) -> None:
        _, ax = self._run()
        dashed = [line for line in ax.get_lines() if line.get_linestyle() == "--"]
        # Stage 1 runs 2025-01..2025-12, so the transition belongs on 2026-01,
        # not on the last month of stage 1 and not one month past it.
        assert pd.Timestamp(dashed[0].get_xdata()[0]) == pd.Timestamp("2026-01-01")

    def test_hides_scenarios_after_the_money_runs_out(self) -> None:
        self._run()
        # A depleted scenario must flatline at zero on the chart rather than
        # dragging the bands into negative territory.
        self.plan.monte_carlo_wealth.assert_called_once_with(discounting="fv", include_negative_values=False)

    def test_labels_the_axis_with_the_plan_currency(self) -> None:
        _, ax = self._run()
        assert ax.get_ylabel() == "Wealth (USD)"

    def test_labels_every_stage(self) -> None:
        _, ax = self._run()
        assert sorted(text.get_text() for text in ax.texts) == ["accumulation", "retirement"]

    def test_save_path_writes_the_png(self, tmp_path) -> None:
        target = tmp_path / "plan.png"
        out, _ = self._run(save_path=str(target))
        assert isinstance(out, list)
        assert target.read_bytes().startswith(PNG_MAGIC)

    @pytest.mark.asyncio
    async def test_registered(self) -> None:
        from okama_mcp.server import mcp

        names = {t.name for t in await mcp.list_tools()}
        assert {"plot_finplan_forecast", "finplan_forecast", "finplan_backtest"} <= names
