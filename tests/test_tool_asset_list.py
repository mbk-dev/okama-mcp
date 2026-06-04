"""Tests for tools/asset_list.py: compare_assets, get_correlations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from okama_mcp.errors import OkamaMcpError
from okama_mcp.tools import asset_list as al_tool


def _make_asset_list_mock(*, describe_df, ror_df, symbols, ccy="USD",
                         first_date="2010-01-31", last_date="2024-12-31",
                         inflation_attr=None):
    mock = SimpleNamespace()
    mock.symbols = symbols
    mock.currency = ccy
    mock.first_date = pd.Timestamp(first_date)
    mock.last_date = pd.Timestamp(last_date)
    mock.assets_ror = ror_df
    mock.describe = lambda: describe_df
    if inflation_attr:
        mock.inflation = inflation_attr
    return mock


class TestCompareAssets:
    def test_returns_describe_table(self) -> None:
        describe = pd.DataFrame(
            {
                "GLD.US": [0.085, 0.18, -0.30],
                "VNQ.US": [0.072, 0.21, -0.55],
                "inflation": [0.025, 0.012, None],
            },
            index=["CAGR (10 years)", "Risk", "Max drawdown"],
        )
        ror = pd.DataFrame(
            {"GLD.US": [0.01, 0.02], "VNQ.US": [0.03, -0.01]},
            index=pd.period_range("2024-01", periods=2, freq="M"),
        )
        mock = _make_asset_list_mock(
            describe_df=describe, ror_df=ror,
            symbols=["GLD.US", "VNQ.US"],
        )
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock) as m:
            out = al_tool.compare_assets(["GLD.US", "VNQ.US"], ccy="USD")

        m.assert_called_once_with(
            ["GLD.US", "VNQ.US"],
            ccy="USD",
            first_date=None,
            last_date=None,
            inflation=True,
        )
        assert out["symbols"] == ["GLD.US", "VNQ.US"]
        assert out["ccy"] == "USD"
        assert out["first_date"] == "2010-01-31"
        assert out["last_date"] == "2024-12-31"
        assert out["describe"]["columns"] == ["GLD.US", "VNQ.US", "inflation"]
        assert "CAGR (10 years)" in out["describe"]["index"]

    def test_inflation_off_passed_through(self) -> None:
        mock = _make_asset_list_mock(
            describe_df=pd.DataFrame({"x": [1]}),
            ror_df=pd.DataFrame({"x": [1.0]}),
            symbols=["X.US"],
        )
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock) as m:
            al_tool.compare_assets(["X.US"], inflation=False)
        kwargs = m.call_args.kwargs
        assert kwargs["inflation"] is False

    def test_empty_assets_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            al_tool.compare_assets([])

    def test_okama_value_error_translated(self) -> None:
        with patch(
            "okama_mcp.tools.asset_list.ok.AssetList",
            side_effect=ValueError("ZZZ is not in the list of assets"),
        ):
            with pytest.raises(OkamaMcpError) as ei:
                al_tool.compare_assets(["ZZZ.US"])
        assert "search_assets" in str(ei.value).lower()


class TestGetCorrelations:
    def test_returns_correlation_matrix(self) -> None:
        idx = pd.period_range("2024-01", periods=12, freq="M")
        # Construct ror DataFrame where corr is computable and predictable.
        ror = pd.DataFrame(
            {
                "A.US": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12],
                "B.US": [-0.01, -0.02, -0.03, -0.04, -0.05, -0.06, -0.07, -0.08, -0.09, -0.10, -0.11, -0.12],
            },
            index=idx,
        )
        mock = _make_asset_list_mock(
            describe_df=pd.DataFrame(), ror_df=ror,
            symbols=["A.US", "B.US"],
        )
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock):
            out = al_tool.get_correlations(["A.US", "B.US"])

        assert out["symbols"] == ["A.US", "B.US"]
        # Perfectly anti-correlated by construction
        corr = out["correlations"]
        # Find row/col indices
        col_a = corr["columns"].index("A.US")
        col_b = corr["columns"].index("B.US")
        row_a = corr["index"].index("A.US")
        row_b = corr["index"].index("B.US")
        assert corr["data"][row_a][col_a] == 1.0
        assert corr["data"][row_b][col_b] == 1.0
        assert corr["data"][row_a][col_b] == -1.0

    def test_inflation_excluded_from_correlations(self) -> None:
        """Inflation column is part of ror_df when inflation=True; it should be dropped
        from the correlation matrix because correlating returns with inflation is rarely useful."""
        idx = pd.period_range("2024-01", periods=12, freq="M")
        ror = pd.DataFrame(
            {
                "A.US": list(range(12)),
                "B.US": list(range(12, 24)),
                "USD.INFL": [0.01] * 12,
            },
            index=idx,
        )
        mock = _make_asset_list_mock(
            describe_df=pd.DataFrame(), ror_df=ror,
            symbols=["A.US", "B.US"],
            inflation_attr="USD.INFL",
        )
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock):
            out = al_tool.get_correlations(["A.US", "B.US"])

        assert "USD.INFL" not in out["correlations"]["columns"]


class TestRollingRisk:
    def test_returns_dataframe_payload(self) -> None:
        idx = pd.period_range("2021-01", periods=4, freq="M")
        al = SimpleNamespace()
        al.get_rolling_risk_annual = MagicMock(return_value=pd.DataFrame(
            {"SPY.US": [0.15, 0.16, 0.14, 0.15], "BND.US": [0.05, 0.05, 0.06, 0.05]},
            index=idx))
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=al):
            out = al_tool.get_rolling_risk(["SPY.US", "BND.US"], "USD", window_months=24)

        al.get_rolling_risk_annual.assert_called_once_with(window=24)
        assert out["window_months"] == 24
        assert out["rolling_risk_annual"]["columns"] == ["SPY.US", "BND.US"]

    def test_empty_symbols_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            al_tool.get_rolling_risk([], "USD")


class TestDividendInfo:
    def test_returns_compact_dividend_summary(self) -> None:
        idx = pd.period_range("2024-01", periods=3, freq="M")
        al = SimpleNamespace()
        al.dividend_yield = pd.DataFrame(
            {"SPY.US": [0.013, 0.0125, 0.012], "VNQ.US": [0.039, 0.0385, 0.0385]},
            index=idx)
        al.get_dividend_mean_yield = MagicMock(return_value=pd.Series(
            {"SPY.US": 0.0140, "VNQ.US": 0.0364}))
        years_idx = [2023, 2024]
        al.dividend_paying_years = pd.DataFrame(
            {"SPY.US": [9, 10], "VNQ.US": [9, 10]}, index=years_idx)
        al.dividend_growing_years = pd.DataFrame(
            {"SPY.US": [8, 9], "VNQ.US": [2, 0]}, index=years_idx)
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=al):
            out = al_tool.get_dividend_info(["SPY.US", "VNQ.US"], "USD")

        assert out["ltm_dividend_yield"] == {"SPY.US": 0.012, "VNQ.US": 0.0385}
        assert out["mean_yield_5y"] == {"SPY.US": 0.0140, "VNQ.US": 0.0364}
        assert out["paying_years_streak"] == {"SPY.US": 10, "VNQ.US": 10}
        assert out["growing_years_streak"] == {"SPY.US": 9, "VNQ.US": 0}
        al.get_dividend_mean_yield.assert_called_once_with(period=5)


class TestServerRegistration:
    @pytest.mark.asyncio
    async def test_phase3_tools_registered(self) -> None:
        from okama_mcp.server import mcp

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert "get_asset_history" in names
        assert "compare_assets" in names
        assert "get_correlations" in names
        assert "get_rolling_risk" in names
        assert "get_dividend_info" in names
