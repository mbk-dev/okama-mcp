"""Exercise the optional household planner through the actual MCP boundary."""

from __future__ import annotations

import importlib.util
import json
import socket
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
