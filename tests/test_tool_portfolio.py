"""Tests for tools/portfolio.py: analyze_portfolio, drawdowns, var/cvar, wealth_index."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from okama_mcp.errors import OkamaMcpError
from okama_mcp.tools import portfolio as pf_tool


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Ensure each test starts with an empty portfolio cache."""
    pf_tool.clear_cache()


def _make_portfolio_mock(
    *,
    symbols=("GLD.US", "VNQ.US"),
    weights=(0.3, 0.7),
    ccy="USD",
    first_date="2010-01-01",
    last_date="2024-12-31",
    period_length=15.0,
    wealth=None,
    drawdowns=None,
    recovery=None,
    describe=None,
    cagr=0.0823,
    mean_return_annual=0.0850,
    risk_annual=0.156,
    var=0.084,
    cvar=0.123,
) -> SimpleNamespace:
    idx = pd.period_range("2010-01", periods=6, freq="M")
    # Real okama Portfolio.wealth_index is ALWAYS a DataFrame: the portfolio column
    # plus an accumulated-inflation column when inflation=True (see okama
    # portfolios/core.py, _make_df_if_series).
    wealth = wealth if wealth is not None else pd.DataFrame(
        {
            "pf.PF": [1000.0, 1010.0, 1020.0, 1015.0, 1030.0, 1050.0],
            "USD.INFL": [1000.0, 1002.0, 1004.5, 1006.0, 1008.2, 1010.1],
        },
        index=idx,
    )
    drawdowns = drawdowns if drawdowns is not None else pd.Series(
        [0.0, 0.0, 0.0, -0.005, 0.0, 0.0], index=idx, name="dd")
    recovery = recovery if recovery is not None else pd.Series(
        [0, 0, 0, 1, 0, 0], index=idx, name="rp")
    describe = describe if describe is not None else pd.DataFrame(
        {"pf": [cagr, risk_annual]}, index=["CAGR (inception)", "Risk"]
    )

    pf = SimpleNamespace()
    pf.symbols = list(symbols)
    pf.weights = list(weights)
    pf.currency = ccy
    pf.first_date = pd.Timestamp(first_date)
    pf.last_date = pd.Timestamp(last_date)
    pf.period_length = period_length
    pf.symbol = "pf.PF"
    pf.wealth_index = wealth
    pf.drawdowns = drawdowns
    pf.recovery_period = recovery
    pf.mean_return_annual = mean_return_annual
    pf.risk_annual = risk_annual
    pf.describe = lambda: describe
    pf.get_cagr = MagicMock(return_value=pd.DataFrame({"pf": [cagr], "inflation": [0.025]},
                                                     index=["CAGR (inception)"]))
    pf.get_var_historic = MagicMock(return_value=var)
    pf.get_cvar_historic = MagicMock(return_value=cvar)
    idx_roll = pd.period_range("2011-01", periods=4, freq="M")
    pf.get_rolling_cagr = MagicMock(return_value=pd.DataFrame(
        {"pf": [0.05, 0.06, 0.055, 0.07]}, index=idx_roll))
    pf.percentile_inverse_cagr = MagicMock(return_value=8.4)
    return pf


VALID_SPEC: dict = {
    "assets": ["GLD.US", "VNQ.US"],
    "weights": [0.3, 0.7],
    "ccy": "USD",
    "first_date": "2010-01",
    "last_date": "2024-12",
    "rebalancing_strategy": {"period": "year"},
    "inflation": True,
}


class TestAnalyzePortfolio:
    def test_returns_metrics_and_describe(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf) as m, \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB") as reb:
            out = pf_tool.analyze_portfolio(VALID_SPEC)

        m.assert_called_once()
        reb.assert_called_once_with(period="year", abs_deviation=None, rel_deviation=None)
        kwargs = m.call_args.kwargs
        assert kwargs["assets"] == ["GLD.US", "VNQ.US"]
        assert kwargs["weights"] == [0.3, 0.7]
        assert kwargs["ccy"] == "USD"
        assert kwargs["first_date"] == "2010-01"
        assert kwargs["last_date"] == "2024-12"
        assert kwargs["inflation"] is True
        assert kwargs["rebalancing_strategy"] == "REB"

        assert out["spec"]["assets"] == ["GLD.US", "VNQ.US"]
        assert out["weights"] == {"GLD.US": 0.3, "VNQ.US": 0.7}
        assert out["metrics"]["cagr"] == 0.0823
        assert out["metrics"]["risk_annual"] == 0.156
        assert out["metrics"]["mean_return_annual"] == 0.085
        assert out["describe"]["columns"] == ["pf"]
        assert out["period_years"] == 15.0

    def test_rebalancing_deviations_passed_to_okama(self) -> None:
        pf = _make_portfolio_mock()
        spec = dict(
            VALID_SPEC,
            rebalancing_strategy={
                "period": "quarter",
                "abs_deviation": 0.05,
                "rel_deviation": 0.1,
            },
        )
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB") as reb:
            pf_tool.analyze_portfolio(spec)

        reb.assert_called_once_with(period="quarter", abs_deviation=0.05, rel_deviation=0.1)

    def test_spec_validation_failure_is_translated(self) -> None:
        bad = dict(VALID_SPEC, weights=[0.3, 0.3])  # sum 0.6
        with pytest.raises(OkamaMcpError):
            pf_tool.analyze_portfolio(bad)

    def test_empty_assets_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            pf_tool.analyze_portfolio({"assets": []})

    def test_okama_value_error_translated(self) -> None:
        with patch(
            "okama_mcp.tools.portfolio.ok.Portfolio",
            side_effect=ValueError("ZZZ is not in the list of assets"),
        ), patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            with pytest.raises(OkamaMcpError) as ei:
                pf_tool.analyze_portfolio(VALID_SPEC)
        assert "search_assets" in str(ei.value).lower()

    def test_portfolio_is_cached_between_calls(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf) as m, \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            pf_tool.analyze_portfolio(VALID_SPEC)
            pf_tool.analyze_portfolio(VALID_SPEC)
            pf_tool.analyze_portfolio(VALID_SPEC)
        assert m.call_count == 1

    def test_different_spec_misses_cache(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf) as m, \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            pf_tool.analyze_portfolio(VALID_SPEC)
            other = dict(VALID_SPEC, weights=[0.5, 0.5])
            pf_tool.analyze_portfolio(other)
        assert m.call_count == 2


class TestPortfolioDrawdowns:
    def test_returns_drawdowns_and_recovery(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.get_portfolio_drawdowns(VALID_SPEC)

        assert out["max_drawdown"] == -0.005
        assert out["max_recovery_months"] == 1
        assert "drawdowns" in out
        assert out["drawdowns"]["values"][3] == -0.005


class TestPortfolioVarCvar:
    def test_default_params(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.get_portfolio_var_cvar(VALID_SPEC)

        pf.get_var_historic.assert_called_once_with(time_frame=12, level=1)
        pf.get_cvar_historic.assert_called_once_with(time_frame=12, level=1)
        assert out["var"] == 0.084
        assert out["cvar"] == 0.123
        assert out["time_frame_months"] == 12
        assert out["level_percent"] == 1

    def test_custom_params(self) -> None:
        pf = _make_portfolio_mock(var=0.20, cvar=0.30)
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.get_portfolio_var_cvar(VALID_SPEC, time_frame=60, level=5)
        pf.get_var_historic.assert_called_once_with(time_frame=60, level=5)
        assert out["time_frame_months"] == 60
        assert out["level_percent"] == 5

    def test_level_must_be_between_0_and_100(self) -> None:
        with pytest.raises(OkamaMcpError):
            pf_tool.get_portfolio_var_cvar(VALID_SPEC, level=120)


class TestPortfolioWealthIndex:
    def test_returns_dataframe_with_portfolio_and_inflation_columns(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.get_portfolio_wealth_index(VALID_SPEC)

        assert out["wealth_index"]["columns"] == ["pf.PF", "USD.INFL"]
        assert out["wealth_index"]["index"][0] == "2010-01-31"
        assert out["wealth_index"]["data"][0] == [1000.0, 1000.0]
        assert out["wealth_index"]["data"][-1] == [1050.0, 1010.1]


class TestRollingCagr:
    def test_returns_dataframe_payload(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.get_rolling_cagr(VALID_SPEC, window_months=24, real=True)

        pf.get_rolling_cagr.assert_called_once_with(window=24, real=True)
        assert out["window_months"] == 24
        assert out["real"] is True
        assert out["rolling_cagr"]["columns"] == ["pf"]
        assert out["rolling_cagr"]["data"][0] == [0.05]

    def test_invalid_window_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            pf_tool.get_rolling_cagr(VALID_SPEC, window_months=0)


class TestCagrProbability:
    def test_returns_percentile_rank(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.get_cagr_probability(VALID_SPEC, years=3, cagr_target=0.0)

        pf.percentile_inverse_cagr.assert_called_once_with(years=3, score=0.0)
        assert out["percentile_rank"] == 8.4
        assert out["years"] == 3
        assert out["cagr_target"] == 0.0
        assert "8.4" in out["interpretation"]


class TestServerRegistration:
    @pytest.mark.asyncio
    async def test_phase4_tools_registered(self) -> None:
        from okama_mcp.server import mcp

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert "analyze_portfolio" in names
        assert "get_portfolio_drawdowns" in names
        assert "get_portfolio_var_cvar" in names
        assert "get_portfolio_wealth_index" in names
        assert "get_rolling_cagr" in names
        assert "get_cagr_probability" in names
