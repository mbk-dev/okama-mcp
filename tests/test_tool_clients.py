"""Actual MCP safe client and versioned plan tools on synthetic local data."""
import json
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP


def response_data(response: object) -> object:
    return json.loads(response.content[0].text) if response.content else response.structured_content["result"]


def registry(tmp_path: Path) -> tuple[FastMCP, Path, str]:
    from okama_planner.storage import PlannerStore
    from okama_mcp.tools import clients

    path = tmp_path / "clients.sqlite3"
    with PlannerStore.initialize(path) as store:
        record = store.create_client({"full_name": "Synthetic Private Person", "email": "private@example.invalid"})
    server = FastMCP("local-clients")
    clients.register(server, path)
    return server, path, record["code"]


@pytest.mark.asyncio
async def test_safe_update_residency_and_restart(tmp_path: Path) -> None:
    from okama_mcp.tools import clients
    server, path, code = registry(tmp_path)
    async with Client(server) as client:
        names = {t.name for t in await client.list_tools()}
        assert names == {"client_get", "client_list", "client_update", "client_set_tax_residency",
                         "client_get_tax_residency", "client_save_plan", "client_load_plan",
                         "client_list_plans", "client_forecast"}
        updated = response_data(await client.call_tool_mcp("client_update", {
            "code": code, "changes": {"sex": "female", "birth_year": 1980}}))
        assert updated["sex"] == "female"
        for changes in ({"email": "private@example.invalid"}, {"full_name": "Private"}, {"unknown": "bad"}):
            invalid = await client.call_tool_mcp("client_update", {"code": code, "changes": changes})
            assert invalid.is_error
        for country in ("ru", "DE"):
            residency = response_data(await client.call_tool_mcp("client_set_tax_residency", {
                "code": code, "residency": {"year": 2026, "country": country}}))
            assert residency["country"] == country.upper()
        invalid = await client.call_tool_mcp("client_set_tax_residency", {
            "code": code, "residency": {"year": 2026, "country": "RU", "note": "Private"}})
        assert invalid.is_error
    restarted = FastMCP("restarted")
    clients.register(restarted, path)
    async with Client(restarted) as client:
        saved = response_data(await client.call_tool_mcp("client_get", {"code": code}))
        assert saved["birth_year"] == 1980
        assert "Private" not in json.dumps(saved)
        assert "private@example.invalid" not in json.dumps(saved)
        assert response_data(await client.call_tool_mcp("client_get_tax_residency", {
            "code": code, "year": 2026}))["country"] == "DE"
        assert response_data(await client.call_tool_mcp("client_get_tax_residency", {
            "code": code, "year": 2025})) is None


@pytest.mark.asyncio
async def test_plan_versions_saved_loaded_and_forecast_inside_planner(tmp_path: Path) -> None:
    server, _, code = registry(tmp_path)
    request = json.loads((Path(__file__).parents[1] / "examples/planner/modes-single-request.json").read_text())
    request["plan"]["assets"][0]["label"] = "PRIVATE_SYNTHETIC_PLAN_LABEL"
    async with Client(server) as client:
        records = []
        for _ in range(2):
            result = await client.call_tool_mcp("client_save_plan", {"code": code, "request": request})
            assert not result.is_error, result.content
            record = response_data(result)
            assert set(record) == {"code", "version"}
            assert record["code"] == code
            records.append(record)
        assert records[0]["version"] != records[1]["version"]
        assert response_data(await client.call_tool_mcp("client_list_plans", {"code": code})) == records
        loaded = await client.call_tool_mcp("client_load_plan", records[0])
        assert not loaded.is_error, loaded.content
        assert "PRIVATE_SYNTHETIC_PLAN_LABEL" not in loaded.model_dump_json()
        forecast = await client.call_tool_mcp("client_forecast", records[0])
        assert not forecast.is_error, forecast.content
        assert "PRIVATE_SYNTHETIC_PLAN_LABEL" not in forecast.model_dump_json()
        assert response_data(forecast)["metrics"]["terminal_p50"] == 50


def test_registry_does_not_create_missing_database(tmp_path: Path) -> None:
    from okama_mcp.tools import clients
    with pytest.raises((FileNotFoundError, ValueError)):
        clients.register(FastMCP("missing"), tmp_path / "missing.sqlite3")
