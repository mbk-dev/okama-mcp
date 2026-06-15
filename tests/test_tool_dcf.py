"""Tests for tools/dcf.py (offline, mocked okama)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from okama_mcp.tools import dcf as dcf_tool
from okama_mcp.tools import portfolio as pf_tool


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    pf_tool.clear_cache()


VALID_PF_SPEC: dict = {
    "assets": ["GLD.US", "VNQ.US"],
    "weights": [0.3, 0.7],
    "ccy": "USD",
    "rebalancing_strategy": {"period": "year"},
    "inflation": True,
}
VALID_MC_SPEC: dict = {"distribution": "norm", "period_years": 10, "scenarios": 50, "percentiles": [5, 50, 95]}
VALID_CASHFLOW: dict = {
    "type": "indexation",
    "initial_investment": 100_000.0,
    "frequency": "year",
    "amount": -5_000.0,
    "indexation": "inflation",
}


def _idx(n: int) -> pd.PeriodIndex:
    return pd.period_range("2015-01", periods=n, freq="M")


def _make_pf_mock_dcf() -> SimpleNamespace:
    pf = SimpleNamespace()
    pf.symbol = "pf.PF"
    pf.symbols = ["GLD.US", "VNQ.US"]
    dcf = SimpleNamespace()
    dcf.set_mc_parameters = MagicMock()
    dcf.discount_rate = 0.04
    dcf.wealth_index = MagicMock(
        return_value=pd.DataFrame({"pf.PF": [100.0, 101.0, 102.0]}, index=_idx(3))
    )
    dcf.cash_flow_ts = MagicMock(return_value=pd.Series([-5.0, -5.0, -5.0], index=_idx(3), name="cf"))
    dcf.wealth_index_fv_with_assets = pd.DataFrame(
        {"pf.PF": [100.0, 101.0], "GLD.US": [50.0, 51.0]}, index=_idx(2)
    )
    dcf.survival_period_hist = MagicMock(return_value=12.5)
    dcf.survival_date_hist = MagicMock(return_value=pd.Timestamp("2027-07-31"))
    dcf.initial_investment_pv = 65_000.0
    dcf.initial_investment_fv = 100_000.0
    dcf.monte_carlo_cash_flow = MagicMock(
        return_value=pd.DataFrame({"s0": [-5.0, -5.1], "s1": [-5.0, -4.9]}, index=_idx(2))
    )
    pf.dcf = dcf
    return pf


def _patches(pf: SimpleNamespace):
    return (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
        patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
    )


def test_get_dcf_wealth_index() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_dcf_wealth_index(VALID_PF_SPEC, VALID_CASHFLOW, discounting="fv", discount_rate=0.05)
    assert out["discounting"] == "fv"
    assert "wealth_index" in out
    pf.dcf.wealth_index.assert_called_once_with(discounting="fv", include_negative_values=False)
    assert pf.dcf.discount_rate == 0.05
    pf.dcf.set_mc_parameters.assert_not_called()


def test_get_dcf_cash_flow_ts() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_dcf_cash_flow_ts(VALID_PF_SPEC, VALID_CASHFLOW, discounting="pv")
    assert out["discounting"] == "pv"
    assert "cash_flow" in out
    pf.dcf.cash_flow_ts.assert_called_once_with(discounting="pv", remove_if_wealth_index_negative=True)


def test_get_dcf_wealth_with_assets() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_dcf_wealth_with_assets(VALID_PF_SPEC, VALID_CASHFLOW)
    assert "wealth_index" in out
    assert out["wealth_index"]["columns"] == ["pf.PF", "GLD.US"]


def test_get_survival_period() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_survival_period(VALID_PF_SPEC, VALID_CASHFLOW, threshold=0.0, discount_rate=0.03)
    assert out["survival_period_years"] == 12.5
    assert out["survival_date"] == "2027-07-31"
    pf.dcf.survival_period_hist.assert_called_once_with(threshold=0.0)
    assert pf.dcf.discount_rate == 0.03


def test_get_initial_investment_values() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_initial_investment_values(VALID_PF_SPEC, VALID_CASHFLOW, discount_rate=0.10)
    assert out["pv"] == 65_000.0
    assert out["fv"] == 100_000.0
    assert out["discount_rate"] == 0.10


def test_get_monte_carlo_cash_flow_bands() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_monte_carlo_cash_flow(VALID_PF_SPEC, VALID_MC_SPEC, VALID_CASHFLOW, discounting="fv")
    assert out["discounting"] == "fv"
    bands = out["cash_flow_paths"]
    assert set(bands["percentiles"].keys()) == {"5", "50", "95"}
    assert bands["n_scenarios"] == 2
    assert bands["n_months"] == 2
    pf.dcf.set_mc_parameters.assert_called_once()
