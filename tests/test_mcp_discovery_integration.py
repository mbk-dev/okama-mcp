"""Opt-in live acceptance for discovery, typed calls and real MCP transports."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from okama_mcp.server import create_server

pytestmark = pytest.mark.integration

PORTFOLIO = {
    "assets": ["SPY.US", "GLD.US"], "weights": [0.6, 0.4], "ccy": "USD",
    "first_date": "2015-01", "last_date": "2020-12", "inflation": False,
}
FRONTIER = {
    "assets": ["SPY.US", "GLD.US"], "ccy": "USD", "first_date": "2015-01", "last_date": "2020-12",
    "bounds": [[0.0, 1.0], [0.0, 1.0]], "n_points": 3,
}
PLAN = {
    "stages": [
        {"portfolio": PORTFOLIO, "period_years": 1,
         "cashflow": {"type": "indexation", "initial_investment": 1000, "frequency": "year", "amount": 10, "indexation": 0}},
        {"portfolio": PORTFOLIO, "period_years": 1,
         "cashflow": {"type": "percentage", "initial_investment": 1000, "frequency": "year", "percentage": -0.03}},
    ],
    "scenarios": 20, "random_seed": 42, "discount_rate": 0,
}


async def call(client: Client, tool: str, arguments: dict[str, Any]) -> Any:
    """Bound each network-dependent operation, retaining normal tool failures."""
    return await asyncio.wait_for(client.call_tool(tool, arguments), timeout=60)


async def test_namespace_catalog_pages_live() -> None:
    async with Client(create_server()) as client:
        catalog = (await call(client, "list_namespaces", {})).data
        assert catalog["usage"]["RATE"]["supports_asset_returns"] is False
        tool_names = {tool.name for tool in await client.list_tools()}
        assert all(set(usage["tools"]) <= tool_names for usage in catalog["usage"].values())
        symbols: list[str] = []
        offset = 0
        for _ in range(30):
            page = (await call(client, "search_assets", {"namespace": "RATE", "limit": 7, "offset": offset})).data
            symbols.extend(row["symbol"] for row in page["results"])
            if not page["has_more"]:
                assert page["next_offset"] is None
                break
            assert page["next_offset"] > offset
            offset = page["next_offset"]
        else:
            pytest.fail("Rate catalog exceeded the bounded pagination probe")
        assert len(symbols) == len(set(symbols)) == page["count"]


@pytest.mark.parametrize("query,namespace,symbol", [
    ("bitcoin", None, "BTC-USD.CC"), ("btc-usd.cc", None, "BTC-USD.CC"),
    ("US78462F1030", "US", "SPY.US"), ("Сбербанк", "MOEX", "SBER.MOEX"),
])
async def test_exact_discovery_live(query: str, namespace: str | None, symbol: str) -> None:
    async with Client(create_server()) as client:
        data = (await call(client, "search_assets", {"query": query, "namespace": namespace})).data
        assert symbol in [row["symbol"] for row in data["results"]]
        if namespace != "MOEX":
            assert data["results"][0]["symbol"] == symbol


async def test_nominal_returns_and_macro_recovery_live() -> None:
    arguments = {"symbols": ["OKID.INDX", "MCFTR.INDX"], "ccy": "RUB",
                 "first_date": "2020-01", "last_date": "2020-12"}
    async with Client(create_server()) as client:
        nominal = (await call(client, "get_asset_returns", {**arguments, "inflation": False})).data
        standard = (await call(client, "get_asset_returns", {**arguments, "inflation": True})).data
        assert nominal["real_mean_return"] is None
        for symbol in arguments["symbols"]:
            assert nominal["cagr"][symbol] == pytest.approx(standard["cagr"][symbol])
        invalid = await client.call_tool_mcp("get_asset_returns", {"symbols": ["RUS_RUB.RATE"]})
        assert invalid.is_error and "get_central_bank_rate" in invalid.content[0].text
        recovered = (await call(client, "get_central_bank_rate", {"country": "RUS_RUB.RATE",
                        "first_date": "2020-01", "last_date": "2020-12"})).data
        assert recovered["symbol"] == "RUS_RUB.RATE"
        assert recovered["values_monthly"]["values"]


async def test_typed_finplan_mc_and_optional_portfolios_live() -> None:
    async with Client(create_server()) as client:
        forecast = (await call(client, "finplan_forecast", {"plan": PLAN})).data
        assert forecast["plan_spec"]["scenarios"] == 20
        mc = (await call(client, "monte_carlo_forecast", {"portfolio": PORTFOLIO,
                  "mc": {"period_years": 1, "scenarios": 20, "random_seed": 42},
                  "cashflow": {"type": "indexation", "initial_investment": 1000, "frequency": "year", "amount": -10, "indexation": 0}})).data
        assert mc["wealth_paths"]["n_scenarios"] == 20
        comparison = (await call(client, "get_asset_returns", {"symbols": ["SPY.US"],
                           "portfolios": [PORTFOLIO], "inflation": False})).data
        assert len(comparison["cagr"]) == 2


@asynccontextmanager
async def wire_client(transport: str, directory: Path) -> AsyncIterator[Client]:
    """Start only a task-owned local server and always reap it after the probe."""
    command = [sys.executable, "-m", "okama_mcp.transport"]
    if transport == "stdio":
        async with Client(StdioTransport(command=command[0], args=[*command[1:], "stdio"],
                          cwd=str(Path.cwd()), log_file=directory / "stdio.log")) as client:
            yield client
        return
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with (directory / "http.log").open("w") as log:
        process = subprocess.Popen([*command, "http", "--port", str(port)], stdout=log, stderr=log)
        try:
            for _ in range(200):
                if process.poll() is not None:
                    pytest.fail(f"HTTP server exited with {process.returncode}; see {log.name}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    await asyncio.sleep(0.1)
            else:
                pytest.fail("HTTP startup exceeded 20 seconds")
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize("transport", ["stdio", "http"])
async def test_real_wire_contracts_and_successful_calls(transport: str, tmp_path: Path) -> None:
    async with wire_client(transport, tmp_path) as client:
        registry = {tool.name: tool.input_schema for tool in await client.list_tools()}
        schema = registry["build_efficient_frontier"]
        assert schema["$defs"]["FrontierSpec"]["properties"]["n_points"]["maximum"] == 200
        frontier = (await call(client, "build_efficient_frontier", {"frontier": FRONTIER})).data
        assert len(frontier["ef_points"]["data"]) >= 3
        nested = {**PORTFOLIO, "assets": [{"assets": ["SPY.US"], "inflation": False}, "GLD.US"]}
        portfolio = (await call(client, "analyze_portfolio", {"portfolio": nested})).data
        assert portfolio["metrics"]["cagr"] is not None
        chart = await call(client, "plot_wealth_index", {"portfolio": nested, "width": 400, "height": 300})
        assert any(block.type == "image" and block.mime_type == "image/png" for block in chart.content)
        invalid = await client.call_tool_mcp("get_asset_info", {"symbol": "USD.INFL"})
        assert invalid.is_error and "get_inflation" in invalid.content[0].text
