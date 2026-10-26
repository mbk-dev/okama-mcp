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

        m.assert_called_once_with("", namespace="US", response_format="frame")
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

    def test_returns_oldest_matching_etfs_with_requested_limit(self) -> None:
        """Protect the "five oldest MOEX BPIFs" discovery workflow.

        MOEX classifies exchange-traded mutual funds (BPIFs) as ``ETF``.  The
        history sort must happen after the type filter and before the response
        limit so the caller receives the truly oldest matching assets.
        """
        df = pd.DataFrame(
            [
                {
                    "symbol": "SNGS.MOEX",
                    "name": "Surgutneftegaz PAO",
                    "type": "Common Stock",
                    "first_date": "1997-05-30",
                    "local_name": "Сургнфгз",
                },
                {
                    "symbol": "LATE.MOEX",
                    "name": "New fund",
                    "type": "ETF",
                    "first_date": "2022-10-01",
                    "local_name": "Новый фонд",
                },
                {
                    "symbol": "SBMX.MOEX",
                    "name": "Sber MOEX Index Fund",
                    "type": "ETF",
                    "first_date": "2018-09-17",
                    "local_name": "Сбер БПИФ МосБиржи",
                },
                {
                    "symbol": "FXUS.MOEX",
                    "name": "FinEx USA UCITS ETF",
                    "type": "ETF",
                    "first_date": "2013-02-28",
                    "local_name": "FinEx USA",
                },
                {
                    "symbol": "UNKNOWN.MOEX",
                    "name": "Undated fund",
                    "type": "ETF",
                    "first_date": None,
                    "local_name": "Без даты",
                },
            ]
        )

        with patch("okama_mcp.tools.search.ok.search", return_value=df) as search:
            result = search_tool.search_assets(
                namespace="MOEX",
                asset_type="ETF",
                oldest_first=True,
                limit=2,
            )

        search.assert_called_once_with("", namespace="MOEX", response_format="frame")
        assert result["count"] == 4
        assert result["truncated"] is True
        assert [row["symbol"] for row in result["results"]] == ["FXUS.MOEX", "SBMX.MOEX"]
        assert result["results"][1]["local_name"] == "Сбер БПИФ МосБиржи"

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

    def test_assets_list_shape_is_enriched_with_descriptions(self) -> None:
        # okama 2.2 returns a bare list of codes for assets_namespaces, not a
        # code->description dict. Descriptions are looked up in the full mapping.
        full = {"US": "US Stocks", "LSE": "London Stock Exchange"}
        with (
            patch.object(search_tool, "_get_assets_namespaces", return_value=["US", "LSE"]),
            patch.object(search_tool, "_get_namespaces", return_value=full),
        ):
            result = search_tool.list_namespaces("assets")
        assert result["namespaces"] == full

    def test_macro_list_shape_is_enriched_with_descriptions(self) -> None:
        full = {"INFL": "Inflation", "RATE": "Central bank rates", "RATIO": "Indicators"}
        with (
            patch.object(
                search_tool, "_get_macro_namespaces", return_value=["INFL", "RATE", "RATIO"]
            ),
            patch.object(search_tool, "_get_namespaces", return_value=full),
        ):
            result = search_tool.list_namespaces("macro")
        assert result["namespaces"] == full

    def test_list_shape_code_without_description_falls_back_to_empty(self) -> None:
        with (
            patch.object(search_tool, "_get_assets_namespaces", return_value=["ZZZ"]),
            patch.object(search_tool, "_get_namespaces", return_value={}),
        ):
            result = search_tool.list_namespaces("assets")
        assert result["namespaces"] == {"ZZZ": ""}

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            search_tool.list_namespaces("crypto")


class TestGetAssetInfo:
    def test_returns_metadata(self) -> None:
        asset_mock = SimpleNamespace(
            symbol="GLD.US",
            name="SPDR Gold Shares",
            local_name="SPDR Gold",
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
        assert result["local_name"] == "SPDR Gold"
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

class TestDiscoveryOrdering:
    def test_exact_bitcoin_name_precedes_more_than_fifty_substring_hits(self) -> None:
        rows = [{"symbol": f"WRAP{i}.US", "ticker": f"WRAP{i}", "name": "Wrapped Bitcoin Fund"} for i in range(60)]
        rows.append({"symbol": "BTC-USD.CC", "ticker": "BTC-USD", "name": "Bitcoin"})
        with patch.object(search_tool.ok, "search", return_value=pd.DataFrame(rows)):
            result = search_tool.search_assets("bitcoin")
        assert result["results"][0]["symbol"] == "BTC-USD.CC"
        assert result["count"] == 61
        assert result["next_offset"] == 50

    @pytest.mark.parametrize("query", ["SPY", "US78462F1030"])
    def test_exact_identifiers_precede_name_matches(self, query: str) -> None:
        rows = [
            {"symbol": "OTHER.US", "ticker": "OTHER", "isin": "", "name": query},
            {"symbol": "SPY.US", "ticker": "SPY", "isin": "US78462F1030", "name": "S&P 500"},
        ]
        with patch.object(search_tool.ok, "search", return_value=pd.DataFrame(rows)):
            result = search_tool.search_assets(query)
        assert result["results"][0]["symbol"] == "SPY.US"

    def test_literal_scoped_search_and_qualified_ticker(self) -> None:
        frame = pd.DataFrame([
            {"symbol": "AAA.US", "ticker": "AAA", "name": "Fund [A]", "local_name": None, "isin": None},
            {"symbol": "BBB.US", "ticker": "BBB", "name": "Fund A", "local_name": "Фонд", "isin": None},
        ])
        with patch.object(search_tool.ok, "search", return_value=frame) as backend:
            result = search_tool.search_assets("[", namespace="us")
        assert [row["symbol"] for row in result["results"]] == ["AAA.US"]
        backend.assert_called_once_with("", namespace="US", response_format="frame")
        with (
            patch.object(search_tool, "_get_namespaces", return_value={"US": "Stocks"}),
            patch.object(search_tool.ok, "search", return_value=frame) as backend,
        ):
            result = search_tool.search_assets("aaa.us")
        assert [row["symbol"] for row in result["results"]] == ["AAA.US"]
        backend.assert_called_once_with("", namespace="US", response_format="frame")

    def test_filtered_pages_are_stable_and_complete(self) -> None:
        frame = pd.DataFrame([
            {"symbol": f"F{i:03}.US", "name": "Fund", "type": "ETF", "first_date": "2020-01-01"}
            for i in range(105)
        ] + [{"symbol": "STOCK.US", "name": "Stock", "type": "Stock", "first_date": None}])
        symbols = []
        for offset in (0, 50, 100, 150):
            with patch.object(search_tool.ok, "search", return_value=frame.sample(frac=1, random_state=offset)):
                page = search_tool.search_assets(namespace="US", asset_type="ETF", oldest_first=True, offset=offset)
            assert page["count"] == 105
            assert page["offset"] == offset
            assert page["limit"] == 50
            assert page["has_more"] == (offset < 100)
            assert page["next_offset"] == (offset + 50 if offset < 100 else None)
            symbols.extend(row["symbol"] for row in page["results"])
        assert symbols == [f"F{i:03}.US" for i in range(105)]

    def test_invalid_offset_is_rejected_before_search(self) -> None:
        with patch.object(search_tool.ok, "search") as backend:
            with pytest.raises(OkamaMcpError, match="offset must be non-negative"):
                search_tool.search_assets("SPY", offset=-1)
        backend.assert_not_called()


@pytest.fixture(autouse=True)
def offline_namespace_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_tool, "_get_assets_namespaces", lambda: ["US", "MOEX", "CC", "INDX"])
    monkeypatch.setattr(search_tool, "_get_macro_namespaces", lambda: ["RATE", "INFL", "RATIO"])


class TestNamespaceCapabilities:
    def test_preserves_descriptions_and_advertises_only_supported_routes(self) -> None:
        namespaces = {code: code for code in ["US", "RATE", "INFL", "RATIO", "NEW", "UNKNOWN"]}
        with (
            patch.object(search_tool, "_get_namespaces", return_value=namespaces),
            patch.object(search_tool, "_get_macro_namespaces", return_value=["RATE", "INFL", "RATIO", "NEW"]),
        ):
            result = search_tool.list_namespaces()
        assert result["namespaces"] == namespaces
        assert result["usage"]["US"]["supports_asset_returns"] is True
        for namespace, tool in [("RATE", "get_central_bank_rate"), ("INFL", "get_inflation"), ("RATIO", "get_indicator")]:
            assert result["usage"][namespace] == {
                "kind": "macro", "supports_asset_returns": False, "tools": [tool, "plot_macro"]
            }
        assert result["usage"]["NEW"] == {"kind": "macro", "supports_asset_returns": False, "tools": []}
        assert result["usage"]["UNKNOWN"] == {"kind": "unknown", "supports_asset_returns": None, "tools": []}

    def test_search_rows_distinguish_asset_and_macro_series(self) -> None:
        rows = [{"symbol": s, "name": "Rate"} for s in ["RUS_RUB.RATE", "OKID.INDX", "FUTURE.NEW"]]
        with patch.object(search_tool.ok, "search", return_value=pd.DataFrame(rows)):
            result = search_tool.search_assets("rate")
        by_symbol = {r["symbol"]: r for r in result["results"]}
        assert by_symbol["RUS_RUB.RATE"]["namespace"] == "RATE"
        assert by_symbol["RUS_RUB.RATE"]["supports_asset_returns"] is False
        assert by_symbol["OKID.INDX"]["supports_asset_returns"] is True
        assert by_symbol["FUTURE.NEW"]["supports_asset_returns"] is None
