"""Tests for tools/asset.py: get_asset_history."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from okama_mcp.errors import OkamaMcpError
from okama_mcp.tools import asset as asset_tool


def _make_asset_mock(*, ror, close_monthly, close_daily, adj_close, dividends, **meta) -> SimpleNamespace:
    return SimpleNamespace(
        ror=ror,
        close_monthly=close_monthly,
        close_daily=close_daily,
        adj_close=adj_close,
        dividends=dividends,
        **meta,
    )


class TestGetAssetHistory:
    def _series(self) -> pd.Series:
        idx = pd.period_range("2024-01", periods=3, freq="M")
        return pd.Series([100.0, 102.0, 105.0], index=idx, name="VNQ.US")

    def test_default_returns_close_monthly(self) -> None:
        s = self._series()
        mock = _make_asset_mock(
            ror=pd.Series(dtype=float),
            close_monthly=s,
            close_daily=pd.Series(dtype=float),
            adj_close=pd.Series(dtype=float),
            dividends=pd.Series(dtype=float),
            symbol="VNQ.US",
            currency="USD",
            first_date=pd.Timestamp("2024-01-01"),
            last_date=pd.Timestamp("2024-03-01"),
        )
        with patch("okama_mcp.tools.asset.ok.Asset", return_value=mock):
            out = asset_tool.get_asset_history("VNQ.US")

        assert out["symbol"] == "VNQ.US"
        assert out["kind"] == "close_monthly"
        assert out["currency"] == "USD"
        assert out["series"]["values"] == [100.0, 102.0, 105.0]
        assert out["series"]["index"][0] == "2024-01-31"

    @pytest.mark.parametrize("kind,attr", [
        ("close_daily", "close_daily"),
        ("adj_close", "adj_close"),
        ("ror", "ror"),
        ("dividends", "dividends"),
    ])
    def test_kind_dispatches_to_correct_property(self, kind: str, attr: str) -> None:
        idx = pd.period_range("2024-01", periods=2, freq="M")
        s = pd.Series([1.0, 2.0], index=idx, name="x")
        kwargs = {a: (s if a == attr else pd.Series(dtype=float)) for a in
                  ("ror", "close_monthly", "close_daily", "adj_close", "dividends")}
        mock = _make_asset_mock(
            symbol="X.US", currency="USD",
            first_date=pd.Timestamp("2024-01-01"),
            last_date=pd.Timestamp("2024-02-29"),
            **kwargs,
        )
        with patch("okama_mcp.tools.asset.ok.Asset", return_value=mock):
            out = asset_tool.get_asset_history("X.US", kind=kind)
        assert out["kind"] == kind
        assert out["series"]["values"] == [1.0, 2.0]

    def test_invalid_kind_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            asset_tool.get_asset_history("X.US", kind="weekly_close")

    def test_date_range_passed_to_okama(self) -> None:
        idx = pd.period_range("2020-01", periods=1, freq="M")
        s = pd.Series([1.0], index=idx)
        mock = _make_asset_mock(
            ror=pd.Series(dtype=float), close_monthly=s,
            close_daily=pd.Series(dtype=float), adj_close=pd.Series(dtype=float),
            dividends=pd.Series(dtype=float),
            symbol="X.US", currency="USD",
            first_date=pd.Timestamp("2020-01-01"),
            last_date=pd.Timestamp("2020-01-31"),
        )
        with patch("okama_mcp.tools.asset.ok.Asset", return_value=mock) as m:
            asset_tool.get_asset_history("X.US", first_date="2020-01", last_date="2020-12")
        m.assert_called_once_with("X.US", first_date="2020-01", last_date="2020-12")

    def test_unknown_symbol_translated(self) -> None:
        with patch(
            "okama_mcp.tools.asset.ok.Asset",
            side_effect=ValueError("ZZZ is not in the list of assets"),
        ):
            with pytest.raises(OkamaMcpError) as ei:
                asset_tool.get_asset_history("ZZZ.US")
        assert "search_assets" in str(ei.value).lower()

    def test_long_series_is_truncated(self) -> None:
        idx = pd.period_range("1970-01", periods=700, freq="M")
        s = pd.Series(range(700), index=idx, dtype=float, name="long")
        mock = _make_asset_mock(
            ror=pd.Series(dtype=float), close_monthly=s,
            close_daily=pd.Series(dtype=float), adj_close=pd.Series(dtype=float),
            dividends=pd.Series(dtype=float),
            symbol="X.US", currency="USD",
            first_date=pd.Timestamp("1970-01-01"),
            last_date=pd.Timestamp("2028-04-30"),
        )
        with patch("okama_mcp.tools.asset.ok.Asset", return_value=mock):
            out = asset_tool.get_asset_history("X.US")
        assert out["series"]["truncated"] is True
        assert out["series"]["total_rows"] == 700
