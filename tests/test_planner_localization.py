"""Stateless language selection over synthetic local MCP tools."""
import json
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP

from okama_mcp.tools import clients, planner


def data(response: object) -> object:
    if not response.content:
        return response.structured_content["result"]
    return json.loads(response.content[0].text)


@pytest.mark.asyncio
async def test_client_language_is_per_call_and_preserves_raw_values(tmp_path: Path) -> None:
    from okama_planner.storage import PlannerStore

    path = tmp_path / "synthetic.sqlite3"
    with PlannerStore.initialize(path) as store:
        record = store.create_client({"full_name": "Synthetic Unabridged Label", "primary_channel": "email",
                                      "email": "synthetic@example.invalid"})
    server = FastMCP("localized-registry")
    clients.register(server, path, language="de")
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert "lokalen" in tools["client_get"].description
        for language in ("ru", "zh", "de", "es", "en", "ru"):
            response = await client.call_tool_mcp("client_get", {"code": record["code"], "language": language})
            assert not response.is_error, response.content
            result = data(response)
            if language == "en":
                assert result["code"] == record["code"]
            else:
                assert result["client"]["code"] == record["code"]
                assert "Synthetic Unabridged Label" not in response.model_dump_json()
                assert "synthetic@example.invalid" not in response.model_dump_json()
        default = data(await client.call_tool_mcp("client_get", {"code": record["code"]}))
        assert default["code"] == record["code"]
        assert default.get("full_name") != record["full_name"]
        bad = await client.call_tool_mcp("client_update", {
            "code": record["code"], "changes": {"unknown": "secret-synthetic-value"}, "language": "ru"})
        assert bad.is_error
        assert "secret-synthetic-value" not in bad.content[0].text
        assert any(text in bad.content[0].text for text in ("Некорректные", "Не удалось", "запрещены"))


@pytest.mark.asyncio
async def test_planner_language_schema_help_and_framework_validation() -> None:
    server = FastMCP("localized-planner")
    planner.register(server, language="ru")
    async with Client(server) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == "planner_forecast")
        assert "план" in tool.description.lower()
        assert tool.input_schema["properties"]["language"]["default"] == "en"
        invalid = await client.call_tool_mcp("planner_forecast", {"request": {}, "language": "ru"})
        assert invalid.is_error
        assert "input_value" not in invalid.content[0].text
        assert "Некорректные" in invalid.content[0].text


def test_startup_language_is_explicit_and_validated() -> None:
    from okama_mcp.transport import build_parser

    parser = build_parser()
    assert parser.parse_args(["stdio"]).language == "en"
    assert parser.parse_args(["stdio", "--language", "zh"]).language == "zh"
    assert parser.parse_args(["http", "--language", "de"]).language == "de"
    with pytest.raises(SystemExit):
        parser.parse_args(["stdio", "--language", "fr"])


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "ru", "de", "es", "zh"])
async def test_report_language_controls_errors_and_description(tmp_path: Path, language: str) -> None:
    from okama_mcp.tools import planner_reports
    from okama_mcp.planner_localization import caption

    server = FastMCP("report-language")
    planner_reports.register(server, tmp_path, language=language)
    async with Client(server) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == "planner_export_report")
        if language != "en":
            assert tool.description == caption("planner_export_report", language)
        result = await client.call_tool_mcp("planner_export_report", {"report": {
            "filename": "../escape.xlsx", "language": language,
            "scenarios": [{"label": "Synthetic full label", "request": {}, "result": {}}]}})
        assert result.is_error
        assert caption("invalid", language) in result.content[0].text
        assert not list(tmp_path.iterdir())




def test_packaged_catalog_has_unique_complete_translations() -> None:
    import csv
    from importlib.resources import files
    from okama_mcp.planner_localization import LANGUAGES

    with files("okama_mcp").joinpath("planner_terminology.csv").open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len({row["key"] for row in rows}) == len(rows)
    assert all(row[language].strip() for row in rows for language in LANGUAGES)


def test_published_companion_fallback_formats_registry_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    from okama_planner import localization
    from okama_mcp.planner_localization import presentation

    monkeypatch.delattr(localization, "client_presentation", raising=False)
    rows = presentation({"created_at": "2026-10-10 12:34:56", "ips_sent_at": "2026-10-09"}, "ru")
    assert rows[0]["value"] == "10.10.2026 12:34:56"
    assert rows[1]["value"] == "09.10.2026"


@pytest.mark.asyncio
async def test_registry_schema_titles_are_localized_without_changing_safe_models(tmp_path: Path) -> None:
    from okama_planner.storage import PlannerStore
    from okama_mcp.schemas import ClientSafeChanges

    original_schema = ClientSafeChanges.model_json_schema()
    path = tmp_path / "synthetic.sqlite3"
    with PlannerStore.initialize(path):
        pass
    server = FastMCP("translated-field-titles")
    clients.register(server, path, language="ru")
    tool = await server.get_tool("client_update")
    details = tool.parameters["properties"]["changes"]
    if "$ref" in details:
        details = tool.parameters["$defs"][details["$ref"].split("/")[-1]]
    assert details["properties"]["sex"]["title"] == "Пол"
    assert ClientSafeChanges.model_json_schema() == original_schema


@pytest.mark.parametrize("defect", ["missing_translation", "duplicate_key", "placeholder"])
def test_catalog_loader_rejects_invalid_packaged_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                     defect: str) -> None:
    import csv
    from okama_mcp import planner_localization as localization

    row = {"key": "sample", **dict.fromkeys(localization.LANGUAGES, "Caption {name}")}
    rows = [row]
    if defect == "missing_translation":
        row["zh"] = " "
    elif defect == "duplicate_key":
        rows.append(row.copy())
    else:
        row["de"] = "Caption {other}"
    with (tmp_path / "planner_terminology.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["key", *localization.LANGUAGES])
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(localization, "files", lambda package: tmp_path)
    localization.captions.cache_clear()
    try:
        with pytest.raises(ValueError):
            localization.captions("ru")
    finally:
        localization.captions.cache_clear()
