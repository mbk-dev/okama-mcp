"""Synthetic personal markers must not cross the MCP boundary or its logs."""
import json
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP

from okama_mcp.tools import clients, planner

MARKER = "PRIVATE_SYNTHETIC_NAME_CONTACT_PATH"


def database(tmp_path: Path) -> tuple[Path, str]:
    from okama_planner.storage import PlannerStore
    path = tmp_path / f"{MARKER}.sqlite3"
    with PlannerStore.initialize(path) as store:
        record = store.create_client({"full_name": MARKER, "email": f"{MARKER}@example.invalid"})
    return path, record["code"]


@pytest.mark.asyncio
async def test_registry_only_exposes_safe_facade_and_fixed_update_schema(tmp_path: Path) -> None:
    path, code = database(tmp_path)
    server = FastMCP("privacy")
    clients.register(server, path)
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert "client_create" not in tools
        assert {"client_save_plan", "client_load_plan", "client_list_plans", "client_forecast"} <= tools.keys()
        for name, args in (("client_get", {"code": code}), ("client_list", {})):
            response = await client.call_tool_mcp(name, args)
            assert not response.is_error
            assert MARKER not in response.model_dump_json()
        schema = tools["client_update"].input_schema
        changes = schema["properties"]["changes"]
        if "$ref" in changes:
            changes = schema["$defs"][changes["$ref"].split("/")[-1]]
        assert set(changes["properties"]) == {"sex", "birth_year", "ips_sent_at"}
        assert changes["additionalProperties"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "ru", "de", "es", "zh", MARKER])
async def test_framework_errors_hide_input_keys_values_and_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                                              language: str) -> None:
    path, code = database(tmp_path)
    server = FastMCP("privacy-errors")
    clients.register(server, path)
    async with Client(server) as client:
        response = await client.call_tool_mcp("client_update", {
            "code": code, "changes": {MARKER: MARKER}, "language": language})
        assert response.is_error
        assert MARKER not in response.model_dump_json()
        assert MARKER not in caplog.text


@pytest.mark.asyncio
async def test_runtime_errors_hide_database_paths_and_causes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                            caplog: pytest.LogCaptureFixture) -> None:
    path, code = database(tmp_path)
    server = FastMCP("privacy-runtime")
    clients.register(server, path)
    async with Client(server) as client:
        response = await client.call_tool_mcp("client_get", {"code": MARKER})
        assert response.is_error
        assert MARKER not in response.model_dump_json()
        assert MARKER not in caplog.text


@pytest.mark.asyncio
async def test_public_forecast_uses_safe_names() -> None:
    request = json.loads((Path(__file__).parents[1] / "examples/planner/baseline-request.json").read_text())
    request["plan"]["assets"][0]["label"] = MARKER
    server = FastMCP("privacy-forecast")
    planner.register(server)
    async with Client(server) as client:
        response = await client.call_tool_mcp("planner_forecast", {"request": request})
        assert not response.is_error
        assert MARKER not in response.model_dump_json()
        assert "privacy_proof" in response.model_dump_json()


@pytest.mark.asyncio
async def test_tool_validation_and_runtime_are_sanitized_before_server_logging(caplog: pytest.LogCaptureFixture) -> None:
    from okama_mcp.planner_localization import register_tool, install_middleware, Language
    from okama_mcp.schemas import PlannerReportSpec

    server = FastMCP("privacy-generic")
    install_middleware(server)

    def failed(report: PlannerReportSpec, language: Language = "en") -> dict:
        raise ValueError(MARKER)

    register_tool(server, failed, "planner_export_report", "en")
    async with Client(server) as client:
        for args in ({"report": {MARKER: MARKER}}, {"report": {"filename": "safe.xlsx", "scenarios": [
                {"label": "safe", "request": {}, "result": {}}]}}):
            response = await client.call_tool_mcp("planner_export_report", args)
            assert response.is_error
            assert MARKER not in response.model_dump_json()
            assert MARKER not in caplog.text


@pytest.mark.asyncio
async def test_report_artifact_and_workbook_are_safe_and_tampering_is_rejected(tmp_path: Path) -> None:
    from okama_mcp.tools import planner_reports
    from okama_planner.ai import forecast
    from openpyxl import load_workbook

    request = json.loads((Path(__file__).parents[1] / "examples/planner/baseline-request.json").read_text())
    request["plan"]["assets"][0]["label"] = MARKER
    scenario = {"label": MARKER, "request": request, "result": forecast(request)}
    server = FastMCP("safe-report")
    planner_reports.register(server, tmp_path)
    async with Client(server) as client:
        response = await client.call_tool_mcp("planner_export_report", {"report": {
            "filename": f"{MARKER}.xlsx", "scenarios": [scenario]}})
        assert not response.is_error, response.content
        assert MARKER not in response.model_dump_json()
        result = json.loads(response.content[0].text)
        assert set(result) == {"filename", "language", "scenarios"}
        assert "/" not in result["filename"] and "\\" not in result["filename"]
        book = load_workbook(tmp_path / result["filename"])
        assert MARKER not in str([list(sheet.values) for sheet in book])
        book.close()
        for change in ("unsigned", "tampered"):
            altered = json.loads(json.dumps(scenario))
            if change == "unsigned":
                del altered["result"]["privacy_proof"]
            else:
                altered["result"]["metrics"]["terminal_p50"] += 100
            rejected = await client.call_tool_mcp("planner_export_report", {"report": {
                "filename": f"{MARKER}.xlsx", "scenarios": [altered]}})
            assert rejected.is_error
            assert MARKER not in rejected.model_dump_json()
            assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "ru", "de", "es", "zh"])
async def test_client_get_language_presents_only_pseudonyms(tmp_path: Path, language: str) -> None:
    path, code = database(tmp_path)
    server = FastMCP("client-safe-languages")
    clients.register(server, path, language=language)
    async with Client(server) as client:
        response = await client.call_tool_mcp("client_get", {"code": code, "language": language})
        assert not response.is_error
        assert MARKER not in response.model_dump_json()
        assert code in response.model_dump_json()
        schema = json.dumps([tool.input_schema for tool in await client.list_tools()])
        assert "ClientDetails" not in schema
        assert '"email"' not in schema
        assert '"full_name"' not in schema


def test_local_brand_identity_file_is_not_read_by_mcp(tmp_path: Path, monkeypatch) -> None:
    from okama_mcp.tools import planner_reports
    brand = tmp_path / 'private-brand.json'
    brand.write_text(json.dumps({'company': MARKER, 'contact': MARKER}))
    original = Path.read_text
    reads = []

    def tracked(path: Path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', tracked)
    planner_reports.register(FastMCP('neutral'), tmp_path, brand)
    assert brand not in reads


@pytest.mark.asyncio
async def test_stored_unconfirmed_symbol_is_rejected_before_crossing_mcp(tmp_path: Path, monkeypatch, caplog) -> None:
    from okama_planner.storage import PlannerStore
    from okama.api import namespaces
    monkeypatch.setattr(namespaces, 'get_namespaces', lambda: {'US': 'Public assets'})
    path, code = database(tmp_path)
    request = json.loads((Path(__file__).parents[1] / 'examples/planner/baseline-request.json').read_text())
    request['return_samples'] = None
    request['plan']['accumulation_holdings'] = [{'symbol': MARKER + '.SMITH', 'weight': 1.0}]
    with PlannerStore.open(path) as store:
        store.save_plan(code, request)
    server = FastMCP('symbol-privacy')
    clients.register(server, path)
    async with Client(server) as client:
        result = await client.call_tool_mcp('client_load_plan', {'code': code, 'version': 1})
        assert result.is_error
        assert MARKER not in result.model_dump_json()
        assert MARKER not in caplog.text


@pytest.mark.asyncio
async def test_old_companion_cannot_fall_back_to_raw_planner_tools(monkeypatch) -> None:
    import sys
    monkeypatch.setitem(sys.modules, 'okama_planner.ai', None)
    server = FastMCP('old-companion')
    planner.register(server)
    assert not any(tool.name.startswith('planner_') for tool in await server.list_tools())
