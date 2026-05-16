"""Tests for the search-and-metadata tools (Phase 2).

The tools wrap ``okama.search``, the namespace dictionaries, and the
``okama.Asset`` constructor. We mock okama at the boundary so the suite runs
offline; an end-to-end test against the live API can be added later.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from okama_mcp.errors import OkamaMcpError
from okama_mcp.tools import search as search_tool


class TestSearchAssets:
    def test_returns_records(self) -> None:
        df = pd.DataFrame(
            [
                {"symbol": "SPY.US", "name": "SPDR S&P 500 ETF", "country": "USA",
                 "exchange": "NYSE ARCA", "currency": "USD", "type": "ETF", "isin": "US78462F1030"},
                {"symbol": "SPYD.US", "name": "SPDR Portfolio S&P 500 High Dividend",
                 "country": "USA", "exchange": "NYSE ARCA", "currency": "USD",
                 "type": "ETF", "isin": "US78464A8541"},
            ]
        )
        with patch("okama_mcp.tools.search.ok.search", return_value=df) as m:
            result = search_tool.search_assets("SPY", namespace="US")

        m.assert_called_once_with("SPY", namespace="US", response_format="frame")
        assert result["count"] == 2
        assert result["results"][0]["symbol"] == "SPY.US"
        assert "SPDR" in result["results"][0]["name"]

    def test_empty_results(self) -> None:
        df = pd.DataFrame(columns=["symbol", "name"])
        with patch("okama_mcp.tools.search.ok.search", return_value=df):
            result = search_tool.search_assets("ZZZZ")
        assert result["count"] == 0
        assert result["results"] == []

    def test_truncates_long_result_set(self) -> None:
        rows = [{"symbol": f"S{i}.US", "name": f"Stock {i}"} for i in range(200)]
        df = pd.DataFrame(rows)
        with patch("okama_mcp.tools.search.ok.search", return_value=df):
            result = search_tool.search_assets("S")
        assert result["count"] == 200
        assert len(result["results"]) == search_tool.MAX_RESULTS
        assert result["truncated"] is True

    def test_okama_value_error_is_translated(self) -> None:
        with patch(
            "okama_mcp.tools.search.ok.search",
            side_effect=ValueError("symbol XXX is not in the list of assets"),
        ):
            with pytest.raises(OkamaMcpError) as ei:
                search_tool.search_assets("XXX")
        assert "search_assets" in str(ei.value).lower()


class TestListNamespaces:
    def test_all(self) -> None:
        fake_ns = {"US": "US Stocks", "MOEX": "Moscow Exchange"}
        with patch.object(search_tool, "_get_namespaces", return_value=fake_ns):
            result = search_tool.list_namespaces("all")
        assert result["kind"] == "all"
        assert result["namespaces"] == fake_ns

    def test_assets(self) -> None:
        fake_ns = {"US": "US Stocks"}
        with patch.object(search_tool, "_get_assets_namespaces", return_value=fake_ns):
            result = search_tool.list_namespaces("assets")
        assert result["namespaces"] == fake_ns

    def test_macro(self) -> None:
        fake_ns = {"INFL": "Inflation rates"}
        with patch.object(search_tool, "_get_macro_namespaces", return_value=fake_ns):
            result = search_tool.list_namespaces("macro")
        assert result["namespaces"] == fake_ns

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            search_tool.list_namespaces("crypto")


class TestGetAssetInfo:
    def test_returns_metadata(self) -> None:
        asset_mock = SimpleNamespace(
            symbol="GLD.US",
            name="SPDR Gold Shares",
            country="USA",
            exchange="NYSE ARCA",
            currency="USD",
            type="ETF",
            isin="US78463V1070",
            first_date=pd.Timestamp("2004-11-18"),
            last_date=pd.Timestamp("2024-12-31"),
            period_length=20.1,
            price=275.45,
        )
        with patch("okama_mcp.tools.search.ok.Asset", return_value=asset_mock) as m:
            result = search_tool.get_asset_info("GLD.US")

        m.assert_called_once_with("GLD.US")
        assert result["symbol"] == "GLD.US"
        assert result["name"] == "SPDR Gold Shares"
        assert result["currency"] == "USD"
        assert result["first_date"] == "2004-11-18"
        assert result["last_date"] == "2024-12-31"
        assert result["period_length_years"] == 20.1

    def test_missing_price_becomes_none(self) -> None:
        asset_mock = MagicMock()
        asset_mock.symbol = "MCFTR.INDX"
        asset_mock.name = "MOEX Total Return"
        asset_mock.country = "Russia"
        asset_mock.exchange = "MOEX"
        asset_mock.currency = "RUB"
        asset_mock.type = "INDX"
        asset_mock.isin = ""
        asset_mock.first_date = pd.Timestamp("1997-09-22")
        asset_mock.last_date = pd.Timestamp("2024-12-31")
        asset_mock.period_length = 27.3
        # Some asset types don't support price — simulate by raising
        type(asset_mock).price = property(
            lambda self: (_ for _ in ()).throw(AttributeError("no price"))
        )

        result = search_tool.get_asset_info("MCFTR.INDX")
        assert result["price"] is None
        assert result["symbol"] == "MCFTR.INDX"

    def test_unknown_symbol_is_translated(self) -> None:
        with patch(
            "okama_mcp.tools.search.ok.Asset",
            side_effect=ValueError("ZZZ is not in the list of assets"),
        ):
            with pytest.raises(OkamaMcpError) as ei:
                search_tool.get_asset_info("ZZZ.US")
        assert "search_assets" in str(ei.value).lower()


class TestServerRegistration:
    """Phase 2 tools must be registered with the FastMCP server."""

    @pytest.mark.asyncio
    async def test_tools_registered(self) -> None:
        from okama_mcp.server import mcp

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert "search_assets" in names
        assert "list_namespaces" in names
        assert "get_asset_info" in names
