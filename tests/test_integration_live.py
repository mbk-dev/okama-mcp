"""Live integration tests against api.okama.io.

These are skipped by default (``pytest -q`` ignores them) because they require
network access and take seconds rather than milliseconds. Run them with:

    poetry run pytest -m integration

They serve as the smoke-test for Phase 8 — end-to-end proof that the FastMCP
server, the tool wrappers, the schemas, and okama all line up against the
real data API. If they pass we're confident a live MCP client will work too.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

pytestmark = pytest.mark.integration


@pytest.fixture
def server():
    from okama_mcp.server import mcp

    return mcp


async def test_search_assets_live(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_assets", {"query": "SPY", "namespace": "US"})
        payload = result.data
    assert payload["count"] > 0
    assert any("SPY" in (row.get("symbol") or "") for row in payload["results"])


async def test_get_inflation_live(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "get_inflation",
            {"currency": "USD", "first_date": "2020-01", "last_date": "2020-12"},
        )
        payload = result.data
    assert payload["symbol"] == "USD.INFL"
    # 12 monthly observations expected
    assert payload["values_monthly"]["values"]


async def test_analyze_portfolio_gold_real_estate_live(server) -> None:
    """User example #1: 30% gold / 70% real estate, full backtest."""
    spec = {
        "assets": ["GLD.US", "VNQ.US"],
        "weights": [0.3, 0.7],
        "ccy": "USD",
        "first_date": "2010-01",
        "last_date": "2024-12",
        "rebalancing_strategy": {"period": "year"},
        "inflation": True,
    }
    async with Client(server) as client:
        result = await client.call_tool("analyze_portfolio", {"portfolio": spec})
        payload = result.data
    assert payload["weights"] == {"GLD.US": 0.3, "VNQ.US": 0.7}
    assert payload["metrics"]["cagr"] is not None
    # Sanity bounds: 15-year CAGR for a gold+REIT mix should be in a plausible band
    assert -0.10 < payload["metrics"]["cagr"] < 0.30


async def test_portfolio_wealth_index_live(server) -> None:
    """Regression for the 2026-06-04 bug: okama wealth_index is a DataFrame
    (portfolio + accumulated inflation), not a Series."""
    spec = {
        "assets": ["GLD.US", "VNQ.US"],
        "weights": [0.3, 0.7],
        "ccy": "USD",
        "first_date": "2010-01",
        "last_date": "2024-12",
        "rebalancing_strategy": {"period": "year"},
        "inflation": True,
    }
    async with Client(server) as client:
        result = await client.call_tool("get_portfolio_wealth_index", {"portfolio": spec})
        payload = result.data
    wi = payload["wealth_index"]
    # Two columns: the portfolio itself and accumulated USD inflation.
    assert len(wi["columns"]) == 2
    assert "USD.INFL" in wi["columns"]
    # ~15 years of monthly rows (below the 500-row truncation threshold).
    assert len(wi["index"]) > 100
    assert len(wi["data"]) == len(wi["index"])
    # Wealth index starts at the initial 1000 units for both columns.
    assert wi["data"][0] == [1000.0, 1000.0]


async def test_monte_carlo_retirement_forecast_live(server) -> None:
    """User example #2: $1k/month indexed-to-inflation withdrawal, 25y horizon."""
    portfolio_spec = {
        "assets": ["SPY.US", "BND.US"],
        "weights": [0.6, 0.4],
        "ccy": "USD",
        "first_date": "2010-01",
        "last_date": "2024-12",
        "rebalancing_strategy": {"period": "year"},
        "inflation": True,
    }
    mc_spec = {
        "distribution": "norm",
        "period_years": 25,
        "scenarios": 100,  # keep it brisk for CI
        "percentiles": [5, 50, 95],
        "random_seed": 42,
    }
    cashflow_spec = {
        "type": "indexation",
        "initial_investment": 1_000_000.0,
        "frequency": "month",
        "amount": -1000.0,
        "indexation": "inflation",
    }
    async with Client(server) as client:
        result = await client.call_tool(
            "monte_carlo_forecast",
            {"portfolio": portfolio_spec, "mc": mc_spec, "cashflow": cashflow_spec},
        )
        payload = result.data
    assert set(payload["wealth_paths"]["percentiles"].keys()) == {"5", "50", "95"}
    assert payload["wealth_paths"]["n_scenarios"] == 100
    survival_pct = payload["survival"]["scenarios_above_zero_pct"]
    assert 0 <= survival_pct <= 100


async def test_plot_wealth_index_live(server) -> None:
    """Chart tools return real PNG image content from live okama data."""
    spec = {
        "assets": ["GLD.US", "VNQ.US"],
        "weights": [0.3, 0.7],
        "ccy": "USD",
        "first_date": "2015-01",
        "last_date": "2024-12",
        "rebalancing_strategy": {"period": "year"},
        "inflation": True,
    }
    async with Client(server) as client:
        result = await client.call_tool("plot_wealth_index", {"portfolio": spec})
    image = result.content[0]
    assert image.type == "image"
    assert image.mimeType == "image/png"


async def test_plot_efficient_frontier_live(server) -> None:
    spec = {
        "assets": ["SPY.US", "BND.US", "GLD.US"],
        "ccy": "USD",
        "n_points": 10,
        "rebalancing_strategy": {"period": "year"},
        "inflation": False,
    }
    async with Client(server) as client:
        result = await client.call_tool("plot_efficient_frontier", {"frontier": spec})
    image = result.content[0]
    assert image.type == "image"
    assert image.mimeType == "image/png"


async def test_rolling_cagr_and_probability_live(server) -> None:
    spec = {
        "assets": ["SPY.US", "BND.US"],
        "weights": [0.6, 0.4],
        "ccy": "USD",
        "first_date": "2010-01",
        "last_date": "2024-12",
        "rebalancing_strategy": {"period": "year"},
        "inflation": True,
    }
    async with Client(server) as client:
        rolling = (await client.call_tool(
            "get_rolling_cagr", {"portfolio": spec, "window_months": 36})).data
        prob = (await client.call_tool(
            "get_cagr_probability", {"portfolio": spec, "years": 3, "cagr_target": 0.0})).data
    assert rolling["rolling_cagr"]["columns"]
    assert len(rolling["rolling_cagr"]["index"]) > 50
    assert 0.0 <= prob["percentile_rank"] <= 100.0


async def test_dividend_info_live(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "get_dividend_info",
            {"symbols": ["SPY.US", "VNQ.US"], "ccy": "USD",
             "first_date": "2015-01", "last_date": "2024-12"},
        )
        payload = result.data
    assert 0.0 < payload["ltm_dividend_yield"]["VNQ.US"] < 0.15
    assert payload["paying_years_streak"]["SPY.US"] >= 1


async def test_compare_assets_with_nested_portfolio_live(server) -> None:
    """Nesting end-to-end: a portfolio used as a single component in compare_assets,
    plus the Sharpe/Sortino enrichment."""
    nested = {
        "assets": ["SPY.US", "AGG.US"],
        "weights": [0.6, 0.4],
        "symbol": "bench6040.PF",
        "inflation": False,
    }
    async with Client(server) as client:
        result = await client.call_tool(
            "compare_assets",
            {
                "symbols": ["GLD.US"],
                "portfolios": [nested],
                "ccy": "USD",
                "first_date": "2015-01",
                "last_date": "2020-01",
                "inflation": False,
            },
        )
        payload = result.data
    assert "GLD.US" in payload["symbols"]
    assert "bench6040.PF" in payload["symbols"]
    assert "bench6040.PF" in payload["sharpe_ratio"]
    assert "GLD.US" in payload["sortino_ratio"]


async def test_analyze_portfolio_nested_and_risk_adjusted_live(server) -> None:
    """A portfolio nested inside another portfolio, with Sharpe/Sortino metrics."""
    spec = {
        "assets": [
            "GLD.US",
            {"assets": ["SPY.US", "AGG.US"], "weights": [0.6, 0.4], "symbol": "core.PF",
             "inflation": False},
        ],
        "weights": [0.3, 0.7],
        "ccy": "USD",
        "first_date": "2015-01",
        "last_date": "2020-01",
        "inflation": False,
    }
    async with Client(server) as client:
        payload = (await client.call_tool(
            "analyze_portfolio", {"portfolio": spec, "rf_return": 0.02})).data
    assert set(payload["weights"]) == {"GLD.US", "core.PF"}
    assert payload["metrics"]["sharpe_ratio"] is not None
    assert payload["metrics"]["sortino_ratio"] is not None


async def test_most_diversified_portfolio_live(server) -> None:
    spec = {"assets": ["SPY.US", "BND.US", "GLD.US"], "ccy": "USD",
            "n_points": 10, "inflation": False}
    async with Client(server) as client:
        payload = (await client.call_tool(
            "get_most_diversified_portfolio", {"frontier": spec})).data
    assert set(payload["weights"]) == {"SPY.US", "BND.US", "GLD.US"}
    assert abs(sum(payload["weights"].values()) - 1.0) < 0.02
    assert payload["diversification_ratio"] is not None


async def test_benchmark_metrics_live(server) -> None:
    async with Client(server) as client:
        payload = (await client.call_tool(
            "get_benchmark_metrics",
            {"benchmark": "SPY.US", "symbols": ["AGG.US", "GLD.US"], "ccy": "USD",
             "first_date": "2015-01", "last_date": "2020-01"})).data
    assert payload["benchmark"] == "SPY.US"
    # The benchmark column is dropped by okama; only the compared assets remain.
    assert "AGG.US" in payload["beta"]
    assert "GLD.US" in payload["correlation"]
    assert "AGG.US" in payload["tracking_error"]


async def test_asset_returns_live(server) -> None:
    async with Client(server) as client:
        ret = (await client.call_tool(
            "get_asset_returns",
            {"symbols": ["SPY.US", "GLD.US"], "ccy": "USD",
             "first_date": "2015-01", "last_date": "2020-01"})).data
        roll = (await client.call_tool(
            "get_rolling_returns",
            {"symbols": ["SPY.US"], "ccy": "USD", "window_months": 24,
             "first_date": "2015-01", "last_date": "2020-01"})).data
    assert "SPY.US" in ret["cagr"]
    assert "SPY.US" in ret["mean_return"]
    assert ret["annual_returns"]["columns"]
    assert roll["rolling_cagr"]["columns"]
    assert len(roll["rolling_cagr"]["index"]) > 1


async def test_plot_transition_map_live(server) -> None:
    spec = {"assets": ["SPY.US", "BND.US", "GLD.US"], "ccy": "USD",
            "n_points": 8, "inflation": False}
    async with Client(server) as client:
        result = await client.call_tool("plot_transition_map", {"frontier": spec})
    image = result.content[0]
    assert image.type == "image"
    assert image.mimeType == "image/png"


async def test_largest_withdrawals_size_live(server) -> None:
    """Slowest live test: the solver runs Monte Carlo iteratively (bounded iter_max)."""
    portfolio_spec = {
        "assets": ["SPY.US", "BND.US"], "weights": [0.6, 0.4], "ccy": "USD",
        "first_date": "2010-01", "last_date": "2024-12", "inflation": True,
    }
    mc_spec = {"distribution": "norm", "period_years": 20, "scenarios": 100,
               "percentiles": [50], "random_seed": 42}
    cashflow_spec = {"type": "percentage", "initial_investment": 1_000_000.0,
                     "frequency": "year", "percentage": -0.04}
    async with Client(server) as client:
        payload = (await client.call_tool(
            "find_the_largest_withdrawals_size",
            {"portfolio": portfolio_spec, "mc": mc_spec, "cashflow": cashflow_spec,
             "goal": "survival_period", "target_survival_period": 15,
             "percentile": 25, "iter_max": 8})).data
    assert payload["goal"] == "survival_period"
    assert isinstance(payload["success"], bool)
    assert payload["withdrawal_rel"] is not None
