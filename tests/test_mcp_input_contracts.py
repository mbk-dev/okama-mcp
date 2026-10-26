"""Verify input contracts as clients see them, rather than only internal models."""

from typing import Any
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastmcp import Client

from okama_mcp.server import create_server
from okama_mcp.schemas import PortfolioSpec


def resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local JSON-schema reference without flattening recursion."""
    if "$ref" in node:
        target = schema
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return target
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "parameter", "fields"),
    [
        ("analyze_portfolio", "portfolio", {"assets", "weights", "ccy"}),
        ("build_efficient_frontier", "frontier", {"assets", "bounds", "n_points"}),
        ("finplan_forecast", "plan", {"stages", "initial_investment", "scenarios"}),
    ],
)
async def test_core_specs_expose_fields(tool: str, parameter: str, fields: set[str]) -> None:
    async with Client(create_server()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    schema = tools[tool].input_schema
    spec = resolve(schema, schema["properties"][parameter])
    assert fields <= spec.get("properties", {}).keys()
    assert spec["additionalProperties"] is False
    if parameter == "frontier":
        assert spec["properties"]["n_points"]["minimum"] == 2
        assert spec["properties"]["n_points"]["maximum"] == 200
        assert spec["properties"]["n_points"]["default"] == 20
    elif parameter == "plan":
        stage = resolve(schema, spec["properties"]["stages"]["items"])
        nested = resolve(schema, stage["properties"]["portfolio"])
        assert "assets" in nested["required"]
    else:
        variants = spec["properties"]["assets"]["items"]["anyOf"]
        assert any("assets" in resolve(schema, item).get("properties", {}) for item in variants)


@pytest.mark.asyncio
async def test_mcp_converts_nested_portfolio_to_typed_spec() -> None:
    from okama_mcp.tools.portfolio import _validate

    received = []

    def capture(spec: PortfolioSpec) -> Any:
        assert isinstance(spec, PortfolioSpec)
        validated = _validate(spec)
        assert isinstance(validated.assets[0], PortfolioSpec)
        received.append(validated)
        raise RuntimeError("STOP_AFTER_VALIDATION")

    with patch("okama_mcp.tools.portfolio._get_portfolio", side_effect=capture):
        async with Client(create_server()) as client:
            await client.call_tool_mcp("analyze_portfolio", {"portfolio": {"assets": [{"assets": ["SPY.US"]}]}})
    assert len(received) == 1
    assert received[0].ccy == "USD"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,parameter,spec,builder_path", [
    ("build_efficient_frontier", "frontier", {"assets": ["SPY.US", "GLD.US"], "n_points": 201},
     "okama_mcp.tools.frontier._get_frontier"),
    ("build_efficient_frontier", "frontier", {"assets": ["SPY.US", "GLD.US"], "bounds": [[0, 1]]},
     "okama_mcp.tools.frontier._get_frontier"),
    ("analyze_portfolio", "portfolio", {"assets": ["SPY.US", "GLD.US"], "weights": [0.5, 0.1]},
     "okama_mcp.tools.portfolio._get_portfolio"),
    ("analyze_portfolio", "portfolio", {"assets": ["SPY.US"], "unknown_field": True},
     "okama_mcp.tools.portfolio._get_portfolio"),
])
async def test_invalid_specs_are_rejected_before_tool_body(
    tool: str, parameter: str, spec: dict[str, Any], builder_path: str,
) -> None:
    with patch(builder_path) as builder:
        async with Client(create_server()) as client:
            result = await client.call_tool_mcp(tool, {parameter: spec})
    assert result.is_error
    builder.assert_not_called()


@pytest.mark.asyncio
async def test_every_financial_input_has_a_structured_contract() -> None:
    expected = {
        "portfolio": {"assets", "weights"}, "frontier": {"assets", "bounds"},
        "plan": {"stages", "scenarios"}, "mc": {"distribution", "scenarios"},
        "portfolios": {"assets", "weights"},
    }
    checked = []
    async with Client(create_server()) as client:
        tools = await client.list_tools()
    for tool in tools:
        schema = tool.input_schema
        for name, raw in schema.get("properties", {}).items():
            if name not in {*expected, "cashflow"}:
                continue
            node = resolve(schema, raw)
            if "anyOf" in node:
                node = resolve(schema, next(v for v in node["anyOf"] if v.get("type") != "null"))
            if name == "portfolios":
                node = resolve(schema, node["items"])
            if name == "cashflow":
                assert node.get("discriminator", {}).get("propertyName") == "type", tool.name
                assert len(node["oneOf"]) == 5
            else:
                assert expected[name] <= node.get("properties", {}).keys(), (tool.name, name)
                assert node["additionalProperties"] is False
            checked.append((tool.name, name))
    assert len(checked) >= 50


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,fields", [
    ("indexation", {"frequency": "year", "amount": -10}),
    ("percentage", {"frequency": "year", "percentage": -0.03}),
    ("time_series", {"events": {"2020-01": -10}}),
    ("vanguard", {"percentage": -0.03}),
    ("cut_if_drawdown", {"amount": -10}),
])
async def test_cashflow_variants_are_typed_at_the_mcp_boundary(kind: str, fields: dict[str, Any]) -> None:
    from pydantic import BaseModel
    from okama_mcp.tools.monte_carlo import _validate_cashflow

    captured = []

    def capture(spec: Any) -> Any:
        assert isinstance(spec, BaseModel)
        captured.append(spec)
        return _validate_cashflow(spec)

    strategy = SimpleNamespace(irr=0.05)
    with (
        patch("okama_mcp.tools.monte_carlo._get_portfolio", return_value=(None, SimpleNamespace(dcf=SimpleNamespace(irr=lambda: 0.05)))),
        patch("okama_mcp.tools.monte_carlo._validate_cashflow", side_effect=capture),
        patch("okama_mcp.tools.monte_carlo._build_cashflow_strategy", return_value=strategy),
    ):
        async with Client(create_server()) as client:
            result = await client.call_tool("get_portfolio_irr", {
                "portfolio": {"assets": ["SPY.US"]},
                "cashflow": {"type": kind, "initial_investment": 1000, **fields},
            })
    assert len(captured) == 1
    assert captured[0].type == kind
    assert result.data["irr"] == 0.05


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol,route", [
    ("RUS_RUB.RATE", "get_central_bank_rate"), ("USD.INFL", "get_inflation"), ("USA_CAPE10.RATIO", "get_indicator"),
])
@pytest.mark.parametrize("context", ["metadata", "returns", "portfolio", "frontier"])
async def test_macro_inputs_provide_safe_mcp_recovery(symbol: str, route: str, context: str) -> None:
    calls = {
        "metadata": ("get_asset_info", {"symbol": symbol}),
        "returns": ("get_asset_returns", {"symbols": ["SPY.US", symbol]}),
        "portfolio": ("analyze_portfolio", {"portfolio": {"assets": [{"assets": [symbol]}]}}),
        "frontier": ("build_efficient_frontier", {"frontier": {"assets": ["SPY.US", symbol]}}),
    }
    tool, arguments = calls[context]
    from contextlib import ExitStack
    import okama as ok
    from okama_mcp.tools import portfolio, frontier
    portfolio.clear_cache()
    frontier.clear_cache()
    with ExitStack() as stack:
        constructors = [stack.enter_context(patch.object(ok, name, side_effect=RuntimeError("PRIVATE_BACKEND_DETAIL")))
                        for name in ["Asset", "AssetList", "Portfolio", "EfficientFrontier"]]
        async with Client(create_server()) as client:
            result = await client.call_tool_mcp(tool, arguments)
    assert result.is_error
    message = " ".join(c.text for c in result.content if c.type == "text")
    assert route in message
    assert "search_assets" in message
    assert "PRIVATE_BACKEND_DETAIL" not in message
    for constructor in constructors:
        constructor.assert_not_called()
