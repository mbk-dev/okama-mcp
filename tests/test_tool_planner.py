"""Exercise the optional household planner through the actual MCP boundary."""

from __future__ import annotations

import importlib.util
import copy
import json
import socket
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP

from okama_mcp.tools import planner

FIXTURES = Path(__file__).parents[1] / "examples" / "planner"

requires_planner = pytest.mark.skipif(
    importlib.util.find_spec("okama_planner") is None, reason="Optional companion package is not installed"
)


@requires_planner
@pytest.mark.asyncio
async def test_planner_schema_and_two_independent_offline_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline planner attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", denied)
    server = FastMCP("planner-control")
    planner.register(server)
    async with Client(server) as client:
        tools = await client.list_tools()
        tool = next(t for t in tools if t.name == "planner_forecast")
        schema = getattr(tool, "input_schema", None) or tool.inputSchema
        assert "request" in schema["properties"]
        request_schema = schema["properties"]["request"]

        def resolve(node: dict) -> dict:
            if "$ref" in node:
                target = schema
                for part in node["$ref"].removeprefix("#/").split("/"):
                    target = target[part]
                return target
            return node

        request_schema = resolve(request_schema)
        plan_schema = resolve(request_schema["properties"]["plan"])
        assert {"assets", "budget_items", "goals", "liabilities"} <= plan_schema["properties"].keys()
        assert planner.get_planner_request_model().model_json_schema()["additionalProperties"] is False
        for name in ("baseline", "deferred", "baseline"):
            request = json.loads((FIXTURES / f"{name}-request.json").read_text())
            response = await client.call_tool_mcp("planner_forecast", {"request": request})
            actual = json.loads(response.content[0].text)
            expected = json.loads((FIXTURES / f"{name}-result.json").read_text())
            for package in ("numpy", "pandas", "scipy", "okama"):
                expected["provenance"][f"{package}_version"] = version(package)
            assert actual == expected


@requires_planner
@pytest.mark.asyncio
async def test_invalid_input_is_reported_as_a_tool_error() -> None:
    server = FastMCP("planner-validation")
    planner.register(server)
    async with Client(server) as client:
        response = await client.call_tool_mcp("planner_forecast", {"request": {}})
        assert response.model_dump(by_alias=True)["isError"]
        assert "validation" in response.content[0].text.lower()
        request = json.loads((FIXTURES / "baseline-request.json").read_text())
        request["unsupported_mode"] = "gamma"
        response = await client.call_tool_mcp("planner_forecast", {"request": request})
        assert response.model_dump(by_alias=True)["isError"]
        assert "unsupported_mode" in response.content[0].text


@pytest.mark.asyncio
async def test_companion_absence_keeps_server_registration_working(monkeypatch: pytest.MonkeyPatch) -> None:
    from okama_mcp.errors import OkamaMcpError

    monkeypatch.setattr(planner, "get_planner_request_model", lambda: None)
    server = FastMCP("without-planner")
    planner.register(server)
    async with Client(server) as client:
        assert not await client.list_tools()
    with pytest.raises(OkamaMcpError, match="install"):
        planner.planner_forecast({})
    with pytest.raises(OkamaMcpError, match="install"):
        planner.planner_compare_modes({}, {})


@requires_planner
@pytest.mark.asyncio
async def test_comparison_exposes_complete_companion_schema_for_both_requests() -> None:
    server = FastMCP("planner-comparison-schema")
    planner.register(server)
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert "planner_compare_modes" in tools
        tool = tools["planner_compare_modes"]
        schema = getattr(tool, "input_schema", None) or tool.inputSchema
        assert set(schema["required"]) == {"baseline", "variant"}
        assert schema["properties"]["baseline"] == schema["properties"]["variant"]
        companion_schema = planner.get_planner_request_model().model_json_schema()

        def normalized(node: object, source: dict) -> object:
            if isinstance(node, list):
                return [normalized(value, source) for value in node]
            if not isinstance(node, dict):
                return node
            if "$ref" in node:
                target = source
                for part in node["$ref"].removeprefix("#/").split("/"):
                    target = target[part]
                return normalized(target, source)
            return {
                key: normalized(value, source)
                for key, value in node.items()
                if key not in {"$defs", "title"}
                and not (key == "default" and isinstance(value, dict))
            }

        # FastMCP inlines refs, removes titles and serializes model defaults independently.
        assert normalized(schema["properties"]["baseline"], schema) == normalized(
            companion_schema, companion_schema
        )


@requires_planner
@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_argument", ["baseline", "variant"])
async def test_comparison_validates_each_request(invalid_argument: str) -> None:
    server = FastMCP("planner-comparison-validation")
    planner.register(server)
    request = json.loads((FIXTURES / "baseline-request.json").read_text())
    arguments = {"baseline": request, "variant": request}
    arguments[invalid_argument] = {}
    async with Client(server) as client:
        response = await client.call_tool_mcp("planner_compare_modes", arguments)
        assert response.model_dump(by_alias=True)["isError"]
        assert "validation" in response.content[0].text.lower()


@requires_planner
@pytest.mark.asyncio
async def test_older_companion_keeps_forecast_available(monkeypatch: pytest.MonkeyPatch) -> None:
    import okama_planner
    from okama_mcp.errors import OkamaMcpError

    monkeypatch.delattr(okama_planner, "compare_portfolio_modes", raising=False)
    server = FastMCP("planner-older-companion")
    planner.register(server)
    async with Client(server) as client:
        assert {tool.name for tool in await client.list_tools()} == {"planner_forecast"}
    request = json.loads((FIXTURES / "baseline-request.json").read_text())
    with pytest.raises(OkamaMcpError, match="upgrade"):
        planner.planner_compare_modes(request, request)


@requires_planner
@pytest.mark.asyncio
async def test_joint_modes_fund_goals_differently_and_replay_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline comparison attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", denied)
    server = FastMCP("planner-joint-modes")
    planner.register(server)
    async with Client(server) as client:
        results = []
        for mode, expected_capital, expected_funding in (
            ("single", 50, 1), ("per_goal", 100, 0), ("single", 50, 1)
        ):
            request = json.loads((FIXTURES / f"modes-{mode}-request.json").read_text())
            response = await client.call_tool_mcp("planner_forecast", {"request": request})
            assert not response.model_dump(by_alias=True)["isError"], response.content[0].text
            actual = json.loads(response.content[0].text)
            assert actual["portfolio_mode"] == mode
            assert actual["metrics"]["terminal_p50"] == expected_capital
            assert actual["goals"][0]["p_funded"] == expected_funding
            results.append(actual)
        assert results[0] == results[2]


@requires_planner
@pytest.mark.asyncio
async def test_joint_comparison_is_stateless_and_rejects_changed_family_inputs() -> None:
    baseline = json.loads((FIXTURES / "modes-single-request.json").read_text())
    variant = json.loads((FIXTURES / "modes-per_goal-request.json").read_text())
    server = FastMCP("planner-controlled-comparison")
    planner.register(server)
    async with Client(server) as client:
        arguments = {"baseline": baseline, "variant": variant}
        response = await client.call_tool_mcp("planner_compare_modes", arguments)
        assert not response.model_dump(by_alias=True)["isError"], response.content[0].text
        actual = json.loads(response.content[0].text)
        assert actual["baseline"]["metrics"]["terminal_p50"] == 50
        assert actual["variant"]["metrics"]["terminal_p50"] == 100
        assert actual["differences"]["direction"] == "variant_minus_baseline"
        assert actual["differences"]["metrics"]["terminal_p50"] == 50
        assert actual["differences"]["goals"] == [{"goal_id": 1, "p_funded": -1, "unmet_mean": 50}]
        assert actual["policy"]["same_allocation"] is True
        assert actual["risk_structure"]["strategies_differ"] is False
        assert set(actual["risk_structure"]["segment_strategies"]) == {"household", "purchase"}
        changed = copy.deepcopy(variant)
        changed["seed"] += 1
        rejected = await client.call_tool_mcp("planner_compare_modes", {"baseline": baseline, "variant": changed})
        assert rejected.model_dump(by_alias=True)["isError"]
        assert "seed" in rejected.content[0].text.lower()
        replay = await client.call_tool_mcp("planner_compare_modes", arguments)
        assert json.loads(replay.content[0].text) == actual


@requires_planner
def test_mode_example_runs_the_stdio_server_and_reports_goal_funding() -> None:
    root = Path(__file__).parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "examples" / "planner_modes_client.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert 'single: full-plan success=1.0; goal funding={"1": 1.0}' in completed.stdout
    assert 'per_goal: full-plan success=0.0; goal funding={"1": 0.0}' in completed.stdout
    saved = json.loads((root / "tmp" / "planner-modes-mcp" / "comparison-result.json").read_text())
    assert saved["baseline"]["goals"][0]["p_funded"] == 1
    assert saved["variant"]["goals"][0]["p_funded"] == 0


def test_schema_loader_accepts_only_an_absent_companion(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from okama_mcp.schemas import get_planner_request_model

    monkeypatch.setitem(sys.modules, "okama_planner", None)
    assert get_planner_request_model() is None


def test_schema_loader_preserves_broken_dependency_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    from okama_mcp.schemas import get_planner_request_model

    original = builtins.__import__

    def broken(name: str, *args: object, **kwargs: object) -> object:
        if name == "okama_planner":
            raise ModuleNotFoundError("Missing nested dependency", name="nested_dependency")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    with pytest.raises(ModuleNotFoundError, match="nested"):
        get_planner_request_model()
