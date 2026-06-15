"""Tests for tools/mc_diagnostics.py (offline, mocked okama)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from okama_mcp.tools import mc_diagnostics as diag
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
VALID_MC_SPEC: dict = {"distribution": "t", "period_years": 10, "scenarios": 100}


def _make_pf_mock_with_mc() -> SimpleNamespace:
    pf = SimpleNamespace()
    pf.symbol = "pf.PF"
    pf.symbols = ["GLD.US", "VNQ.US"]
    dcf = SimpleNamespace()
    dcf.set_mc_parameters = MagicMock()
    mc = SimpleNamespace()
    mc.get_parameters_for_distribution = MagicMock(return_value=(5.0, 0.01, 0.04))
    mc.jarque_bera = {"statistic": 58.3, "p-value": 2e-13}
    mc.kstest = {"statistic": 0.05, "p-value": 0.68}
    mc.kstest_for_all_distributions = pd.DataFrame(
        {"statistic": [0.09, 0.05, 0.04], "p-value": [0.04, 0.68, 0.8]},
        index=["norm", "lognorm", "t"],
    )
    mc.backtesting_error = MagicMock(
        return_value={"delta_arithmetic_mean": 0.001, "delta_var": -0.002, "delta_cvar": 0.003}
    )
    mc.skewness = pd.Series([0.1, 0.2, 0.3], index=pd.period_range("2020-01", periods=3, freq="M"))
    mc.kurtosis = pd.Series([1.1, 1.2, 1.3], index=pd.period_range("2020-01", periods=3, freq="M"))
    mc.skewness_rolling = MagicMock(return_value=pd.Series([0.4, 0.5]))
    mc.kurtosis_rolling = MagicMock(return_value=pd.Series([2.1, 2.2]))
    mc.optimize_df_for_students = MagicMock(return_value=4.7)
    mc.percentile_distribution_cagr = MagicMock(return_value={10: -0.02, 50: 0.05, 90: 0.12})
    mc.percentile_inverse_cagr = MagicMock(return_value=8.0)
    dcf.mc = mc
    pf.dcf = dcf
    return pf


def _patches(pf: SimpleNamespace):
    return (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
    )


def test_get_distribution_fit_shape() -> None:
    pf = _make_pf_mock_with_mc()
    p1, p2 = _patches(pf)
    with p1, p2:
        out = diag.get_distribution_fit(VALID_PF_SPEC, VALID_MC_SPEC)
    assert out["distribution"] == "t"
    assert out["parameters"] == [5.0, 0.01, 0.04]
    assert set(out["jarque_bera"]) == {"statistic", "p-value"}
    assert set(out["kstest"]) == {"statistic", "p-value"}
    assert "kstest_all_distributions" in out
    assert set(out["backtesting_error"]) == {"delta_arithmetic_mean", "delta_var", "delta_cvar"}
    pf.dcf.set_mc_parameters.assert_called_once()


def test_get_return_moments_expanding_and_rolling() -> None:
    pf = _make_pf_mock_with_mc()
    p1, p2 = _patches(pf)
    with p1, p2:
        out = diag.get_return_moments(VALID_PF_SPEC, VALID_MC_SPEC)
        out_roll = diag.get_return_moments(VALID_PF_SPEC, VALID_MC_SPEC, rolling_window=24)
    assert "skewness" in out and "kurtosis" in out
    assert out["rolling_window"] is None
    pf.dcf.mc.skewness_rolling.assert_called_once_with(window=24)
    assert out_roll["rolling_window"] == 24


def test_optimize_students_df() -> None:
    pf = _make_pf_mock_with_mc()
    p1, p2 = _patches(pf)
    with p1, p2:
        out = diag.optimize_students_df(VALID_PF_SPEC, VALID_MC_SPEC, var_level=5)
    assert out["var_level"] == 5
    assert out["degrees_of_freedom"] == 4.7
    pf.dcf.mc.optimize_df_for_students.assert_called_once_with(var_level=5)


def test_get_cagr_distribution() -> None:
    pf = _make_pf_mock_with_mc()
    p1, p2 = _patches(pf)
    with p1, p2:
        out = diag.get_cagr_distribution(VALID_PF_SPEC, VALID_MC_SPEC, percentiles=[10, 50, 90], score=0.0)
    assert out["percentiles"] == {"10": -0.02, "50": 0.05, "90": 0.12}
    assert out["prob_below_score_pct"] == 8.0
    pf.dcf.mc.percentile_distribution_cagr.assert_called_once_with(percentiles=[10, 50, 90])
    pf.dcf.mc.percentile_inverse_cagr.assert_called_once_with(score=0.0)
