"""Tests for tools/plots.py: PNG chart tools."""

import struct
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from fastmcp.utilities.types import Image

import okama_mcp.tools.plots as plots_tool
import okama_mcp.tools.portfolio as pf_tool
import okama_mcp.tools.frontier as fr_tool
from okama_mcp.errors import OkamaMcpError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

VALID_SPEC: dict = {
    "assets": ["GLD.US", "VNQ.US"],
    "weights": [0.3, 0.7],
    "ccy": "USD",
    "first_date": "2010-01",
    "last_date": "2024-12",
    "rebalancing_period": "year",
    "inflation": True,
}


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    pf_tool.clear_cache()
    fr_tool.clear_cache()


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
    "rebalancing_period": "year",
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
