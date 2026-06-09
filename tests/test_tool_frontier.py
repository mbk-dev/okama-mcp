"""Tests for tools/frontier.py: build_efficient_frontier, tangency, GMV."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from okama_mcp.errors import OkamaMcpError
from okama_mcp.tools import frontier as fr_tool


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    fr_tool.clear_cache()


def _make_ef_mock(
    *,
    symbols=("SPY.US", "GLD.US", "BND.US"),
    ef_points: pd.DataFrame | None = None,
    tangency: dict | None = None,
    gmv_weights: np.ndarray | None = None,
    gmv_values: tuple[float, float] = (0.06, 0.045),
) -> SimpleNamespace:
    if ef_points is None:
        ef_points = pd.DataFrame(
            {
                "Risk": [0.05, 0.08, 0.12, 0.18],
                "Mean return": [0.04, 0.07, 0.09, 0.11],
                "CAGR": [0.038, 0.067, 0.085, 0.105],
                symbols[0]: [0.10, 0.30, 0.60, 1.00],
                symbols[1]: [0.20, 0.30, 0.30, 0.00],
                symbols[2]: [0.70, 0.40, 0.10, 0.00],
            }
        )
    if tangency is None:
        tangency = {
            "Weights": np.array([0.50, 0.20, 0.30]),
            "Rate_of_return": 0.082,
            "Risk": 0.115,
        }
    if gmv_weights is None:
        gmv_weights = np.array([0.10, 0.20, 0.70])

    ef = SimpleNamespace()
    ef.symbols = list(symbols)
    ef.currency = "USD"
    ef.first_date = pd.Timestamp("2010-01-01")
    ef.last_date = pd.Timestamp("2024-12-31")
    ef.ef_points = ef_points
    ef.gmv_annual_weights = gmv_weights
    ef.gmv_annual_values = gmv_values
    ef.get_tangency_portfolio = MagicMock(return_value=tangency)
    ef.get_most_diversified_portfolio = MagicMock(
        return_value={
            "SPY.US": 0.30, "GLD.US": 0.30, "BND.US": 0.40,
            "CAGR": 0.071, "Risk": 0.092, "Diversification ratio": 1.42,
        }
    )
    return ef


VALID_FRONTIER_SPEC: dict = {
    "assets": ["SPY.US", "GLD.US", "BND.US"],
    "ccy": "USD",
    "first_date": "2010-01",
    "last_date": "2024-12",
    "n_points": 20,
    "rebalancing_strategy": {"period": "year"},
    "inflation": False,
}


class TestBuildEfficientFrontier:
    def test_returns_ef_points_table(self) -> None:
        ef = _make_ef_mock()
        with (
            patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef) as cls,
            patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB") as reb,
        ):
            out = fr_tool.build_efficient_frontier(VALID_FRONTIER_SPEC)

        reb.assert_called_once_with(period="year", abs_deviation=None, rel_deviation=None)
        kwargs = cls.call_args.kwargs
        assert kwargs["assets"] == ["SPY.US", "GLD.US", "BND.US"]
        assert kwargs["ccy"] == "USD"
        assert kwargs["first_date"] == "2010-01"
        assert kwargs["last_date"] == "2024-12"
        assert kwargs["n_points"] == 20
        assert kwargs["rebalancing_strategy"] == "REB"
        assert kwargs["bounds"] is None

        assert out["symbols"] == ["SPY.US", "GLD.US", "BND.US"]
        assert "Risk" in out["ef_points"]["columns"]
        assert "CAGR" in out["ef_points"]["columns"]

    def test_bounds_converted_to_tuple_of_tuples(self) -> None:
        ef = _make_ef_mock()
        spec = dict(VALID_FRONTIER_SPEC, bounds=[[0.0, 0.5], [0.1, 0.3], [0.0, 1.0]])
        with (
            patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef) as cls,
            patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"),
        ):
            fr_tool.build_efficient_frontier(spec)
        assert cls.call_args.kwargs["bounds"] == ((0.0, 0.5), (0.1, 0.3), (0.0, 1.0))

    def test_bounds_length_must_match_assets(self) -> None:
        spec = dict(VALID_FRONTIER_SPEC, bounds=[[0.0, 0.5], [0.1, 0.3]])  # 2 vs 3 assets
        with pytest.raises(OkamaMcpError):
            fr_tool.build_efficient_frontier(spec)

    def test_minimum_two_assets(self) -> None:
        bad = dict(VALID_FRONTIER_SPEC, assets=["SPY.US"])
        with pytest.raises(OkamaMcpError):
            fr_tool.build_efficient_frontier(bad)

    def test_caching_reuses_constructed_frontier(self) -> None:
        ef = _make_ef_mock()
        with (
            patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef) as cls,
            patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"),
        ):
            fr_tool.build_efficient_frontier(VALID_FRONTIER_SPEC)
            fr_tool.build_efficient_frontier(VALID_FRONTIER_SPEC)
            fr_tool.build_efficient_frontier(VALID_FRONTIER_SPEC)
        assert cls.call_count == 1


class TestGetTangencyPortfolio:
    def test_returns_weights_dict_and_metrics(self) -> None:
        ef = _make_ef_mock()
        with (
            patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef),
            patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"),
        ):
            out = fr_tool.get_tangency_portfolio(VALID_FRONTIER_SPEC, rf_return=0.02)

        ef.get_tangency_portfolio.assert_called_once_with(rf_return=0.02, rate_of_return="cagr")
        assert out["weights"] == {"SPY.US": 0.5, "GLD.US": 0.2, "BND.US": 0.3}
        assert abs(sum(out["weights"].values()) - 1.0) < 1e-9
        assert out["rate_of_return"] == 0.082
        assert out["risk"] == 0.115
        # Sharpe = (return - rf) / risk
        assert abs(out["sharpe_ratio"] - (0.082 - 0.02) / 0.115) < 1e-6

    def test_rate_of_return_mean_passed_through(self) -> None:
        ef = _make_ef_mock()
        with (
            patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef),
            patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"),
        ):
            fr_tool.get_tangency_portfolio(
                VALID_FRONTIER_SPEC, rf_return=0.03, rate_of_return="mean_return"
            )
        ef.get_tangency_portfolio.assert_called_once_with(
            rf_return=0.03, rate_of_return="mean_return"
        )

    def test_invalid_rate_of_return_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            fr_tool.get_tangency_portfolio(VALID_FRONTIER_SPEC, rate_of_return="harmonic")


class TestGetMinVariancePortfolio:
    def test_returns_gmv_weights_and_values(self) -> None:
        ef = _make_ef_mock(
            gmv_weights=np.array([0.10, 0.20, 0.70]),
            gmv_values=(0.06, 0.045),
        )
        with (
            patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef),
            patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"),
        ):
            out = fr_tool.get_min_variance_portfolio(VALID_FRONTIER_SPEC)

        assert out["weights"] == {"SPY.US": 0.1, "GLD.US": 0.2, "BND.US": 0.7}
        assert abs(sum(out["weights"].values()) - 1.0) < 1e-9
        assert out["risk"] == 0.06
        assert out["rate_of_return"] == 0.045

    def test_gmv_risk_lower_than_tangency_risk_invariant(self) -> None:
        """GMV portfolio risk must be ≤ tangency portfolio risk on the same frontier."""
        ef = _make_ef_mock(
            gmv_weights=np.array([0.10, 0.20, 0.70]),
            gmv_values=(0.06, 0.045),
            tangency={"Weights": np.array([0.50, 0.20, 0.30]),
                      "Rate_of_return": 0.082, "Risk": 0.115},
        )
        with (
            patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef),
            patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"),
        ):
            gmv = fr_tool.get_min_variance_portfolio(VALID_FRONTIER_SPEC)
            tangency = fr_tool.get_tangency_portfolio(VALID_FRONTIER_SPEC, rf_return=0.02)
        assert gmv["risk"] <= tangency["risk"]


class TestMostDiversifiedPortfolio:
    def test_returns_weights_and_metrics(self) -> None:
        ef = _make_ef_mock()
        with patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef), \
             patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"):
            out = fr_tool.get_most_diversified_portfolio(
                {"assets": ["SPY.US", "GLD.US", "BND.US"], "ccy": "USD"}
            )
        assert out["weights"] == {"SPY.US": 0.30, "GLD.US": 0.30, "BND.US": 0.40}
        assert out["cagr"] == 0.071
        assert out["risk"] == 0.092
        assert out["diversification_ratio"] == 1.42


def test_build_frontier_resolves_nested_portfolio() -> None:
    from okama_mcp.schemas import FrontierSpec

    spec = FrontierSpec(assets=["GLD.US", {"assets": ["A.US", "B.US"]}])
    with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value="PFOBJ"), \
         patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"), \
         patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"), \
         patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value="EF") as efmock:
        fr_tool._build_frontier(spec)
    assert efmock.call_args.kwargs["assets"] == ["GLD.US", "PFOBJ"]


class TestServerRegistration:
    @pytest.mark.asyncio
    async def test_phase6_tools_registered(self) -> None:
        from okama_mcp.server import mcp

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert "build_efficient_frontier" in names
        assert "get_tangency_portfolio" in names
        assert "get_min_variance_portfolio" in names
        assert "get_most_diversified_portfolio" in names
