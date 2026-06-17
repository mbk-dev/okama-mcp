"""Tests for tools/macro.py: get_inflation, get_central_bank_rate."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from okama_mcp.errors import OkamaMcpError
from okama_mcp.tools import macro as macro_tool


def _make_inflation_mock(*, values=None, cumulative=None, annual=None,
                        symbol="USD.INFL", purchasing_power_1000=425.0) -> SimpleNamespace:
    idx = pd.period_range("2020-01", periods=6, freq="M")
    values = values if values is not None else pd.Series(
        [0.001, 0.002, 0.003, 0.001, 0.002, 0.002], index=idx, name=symbol)
    cumulative = cumulative if cumulative is not None else (values + 1).cumprod() - 1
    annual_idx = pd.PeriodIndex(["2020", "2021"], freq="Y")
    annual = annual if annual is not None else pd.Series([0.012, 0.070], index=annual_idx)

    return SimpleNamespace(
        symbol=symbol,
        name="USA inflation rate",
        country="USA",
        currency="USD",
        type="INFL",
        first_date=pd.Timestamp("2020-01-01"),
        last_date=pd.Timestamp("2020-06-30"),
        values_monthly=values,
        cumulative_inflation=cumulative,
        annual_inflation_ts=annual,
        purchasing_power_1000=purchasing_power_1000,
        rolling_inflation=pd.Series([0.011, 0.012], index=idx[-2:]),
        describe=lambda years=(1, 5, 10): pd.DataFrame(
            {symbol: [0.012, 0.07]}, index=["annual_inflation", "compound"]),
    )


def _make_rate_mock(*, values=None, symbol="US_EFFR.RATE") -> SimpleNamespace:
    idx = pd.period_range("2024-01", periods=4, freq="M")
    values = values if values is not None else pd.Series(
        [0.0525, 0.0500, 0.0475, 0.0450], index=idx, name=symbol)
    daily_idx = pd.date_range("2024-01-01", periods=5, freq="D")
    daily = pd.Series([0.0525, 0.0525, 0.0500, 0.0500, 0.0475], index=daily_idx, name=symbol)
    desc = pd.DataFrame({symbol: [0.05, 0.0488]}, index=["mean", "median"])
    return SimpleNamespace(
        symbol=symbol,
        name="US Federal Reserve rate",
        country="USA",
        currency="USD",
        type="RATE",
        first_date=pd.Timestamp("2024-01-01"),
        last_date=pd.Timestamp("2024-04-30"),
        values_monthly=values,
        values_daily=daily,
        describe=lambda years=(1, 5, 10): desc,
    )


class TestGetInflation:
    def test_currency_is_uppercased_and_namespace_appended(self) -> None:
        infl = _make_inflation_mock(symbol="EUR.INFL")
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl) as cls:
            out = macro_tool.get_inflation("eur")
        cls.assert_called_once_with(symbol="EUR.INFL", first_date=None, last_date=None)
        assert out["symbol"] == "EUR.INFL"

    def test_full_symbol_passed_through(self) -> None:
        infl = _make_inflation_mock(symbol="USD.INFL")
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl) as cls:
            macro_tool.get_inflation("USD.INFL", first_date="2020-01", last_date="2020-06")
        cls.assert_called_once_with(
            symbol="USD.INFL", first_date="2020-01", last_date="2020-06"
        )

    def test_returns_metadata_and_series(self) -> None:
        infl = _make_inflation_mock()
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl):
            out = macro_tool.get_inflation("USD")

        assert out["symbol"] == "USD.INFL"
        assert out["country"] == "USA"
        assert out["currency"] == "USD"
        assert out["first_date"] == "2020-01-01"
        assert out["last_date"] == "2020-06-30"
        assert "values_monthly" in out
        assert "annual_inflation" in out
        assert out["purchasing_power_1000"] == 425.0
        # Cumulative is omitted by default to keep response compact
        assert "cumulative_inflation" not in out

    def test_include_cumulative_flag(self) -> None:
        infl = _make_inflation_mock()
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl):
            out = macro_tool.get_inflation("USD", include_cumulative=True)
        assert "cumulative_inflation" in out

    def test_unknown_symbol_translated(self) -> None:
        with patch(
            "okama_mcp.tools.macro.ok.Inflation",
            side_effect=ValueError("ZZZ is not in the list of assets"),
        ):
            with pytest.raises(OkamaMcpError):
                macro_tool.get_inflation("ZZZ")

    def test_include_rolling_flag(self) -> None:
        infl = _make_inflation_mock()
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl):
            out = macro_tool.get_inflation("USD", include_rolling=True)
        assert "rolling_inflation" in out

    def test_include_describe_flag(self) -> None:
        infl = _make_inflation_mock()
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl):
            out = macro_tool.get_inflation("USD", include_describe=True)
        assert "describe" in out
        assert "columns" in out["describe"]

    def test_rolling_and_describe_absent_by_default(self) -> None:
        infl = _make_inflation_mock()
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl):
            out = macro_tool.get_inflation("USD")
        assert "rolling_inflation" not in out
        assert "describe" not in out


class TestGetCentralBankRate:
    def test_alias_maps_to_real_key_rate_symbol(self) -> None:
        rate = _make_rate_mock(symbol="EU_MRO.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate) as cls:
            macro_tool.get_central_bank_rate("ecb")
        cls.assert_called_once_with(symbol="EU_MRO.RATE", first_date=None, last_date=None)

    def test_us_alias_maps_to_effr(self) -> None:
        rate = _make_rate_mock(symbol="US_EFFR.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate) as cls:
            macro_tool.get_central_bank_rate("US")
        cls.assert_called_once_with(symbol="US_EFFR.RATE", first_date=None, last_date=None)

    def test_full_symbol_passed_through(self) -> None:
        rate = _make_rate_mock(symbol="RUSFAR1M.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate) as cls:
            macro_tool.get_central_bank_rate("RUSFAR1M.RATE", first_date="2024-01")
        cls.assert_called_once_with(symbol="RUSFAR1M.RATE", first_date="2024-01", last_date=None)

    def test_returns_monthly_by_default(self) -> None:
        rate = _make_rate_mock(symbol="US_EFFR.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate):
            out = macro_tool.get_central_bank_rate("US")
        assert out["symbol"] == "US_EFFR.RATE"
        assert out["country"] == "USA"
        assert out["values_monthly"]["values"][0] == 0.0525
        assert "values_daily" not in out
        assert "describe" not in out

    def test_frequency_daily_returns_daily_series(self) -> None:
        rate = _make_rate_mock(symbol="US_EFFR.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate):
            out = macro_tool.get_central_bank_rate("US", frequency="daily")
        assert "values_daily" in out
        assert "values_monthly" not in out
        assert out["values_daily"]["values"][0] == 0.0525

    def test_invalid_frequency_raises(self) -> None:
        rate = _make_rate_mock()
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate):
            with pytest.raises(OkamaMcpError):
                macro_tool.get_central_bank_rate("US", frequency="weekly")

    def test_include_describe_adds_table(self) -> None:
        rate = _make_rate_mock()
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate):
            out = macro_tool.get_central_bank_rate("US", include_describe=True)
        assert "describe" in out
        assert "columns" in out["describe"]

    def test_unknown_country_translated(self) -> None:
        with patch(
            "okama_mcp.tools.macro.ok.Rate",
            side_effect=ValueError("ZZZ.RATE is not in the list of assets"),
        ):
            with pytest.raises(OkamaMcpError):
                macro_tool.get_central_bank_rate("ZZZ")


class TestServerRegistration:
    @pytest.mark.asyncio
    async def test_phase7_tools_registered(self) -> None:
        from okama_mcp.server import mcp

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert "get_inflation" in names
        assert "get_central_bank_rate" in names
