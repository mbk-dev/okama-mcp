"""Local report delegation and installable skill contract."""
import json
from pathlib import Path
import pytest
from fastmcp import Client, FastMCP


@pytest.mark.asyncio
async def test_local_report_export_and_path_boundary(tmp_path: Path) -> None:
    from okama_mcp.tools import planner_reports
    from okama_planner import forecast
    from openpyxl import load_workbook
    request = json.loads((Path(__file__).parents[1] / "examples/planner/modes-single-request.json").read_text())
    scenarios = [{"label": "Synthetic", "request": request, "result": forecast(request)}]
    brand = tmp_path / "brand.json"
    brand.write_text(json.dumps({"company": "Synthetic Practice", "contact": "fiction@example.invalid"}))
    server = FastMCP("local-reports")
    planner_reports.register(server, tmp_path, brand)
    async with Client(server) as client:
        result = await client.call_tool_mcp("planner_export_report", {
            "report": {"scenarios": scenarios, "filename": "synthetic.xlsx", "language": "en"}})
        assert not result.model_dump(by_alias=True)["isError"], result.content
        book = load_workbook(tmp_path / "synthetic.xlsx")
        assert book["Branding"]["B2"].value == "Synthetic Practice"
        book.close()
        original = (tmp_path / "synthetic.xlsx").read_bytes()
        for filename in ("synthetic.xlsx", "../escaped.xlsx", "/escaped.xlsx", "bad.txt"):
            invalid = await client.call_tool_mcp("planner_export_report", {
                "report": {"scenarios": scenarios, "filename": filename}})
            assert invalid.model_dump(by_alias=True)["isError"]
        assert (tmp_path / "synthetic.xlsx").read_bytes() == original


def test_packaged_skill_installs_and_refuses_conflicting_files(tmp_path: Path) -> None:
    from okama_mcp.skills import install_skill
    target = install_skill(tmp_path)
    text = target.read_text()
    assert "client_create" in text and "client_get" in text
    assert "lfp client" not in text
    assert "request_id" in text and "brokers" in text
    assert install_skill(tmp_path) == target
    target.write_text("local customization")
    with pytest.raises(FileExistsError):
        install_skill(tmp_path)


@pytest.mark.asyncio
async def test_public_registration_has_no_local_tools() -> None:
    from okama_mcp.tools import register_all
    server = FastMCP("public")
    register_all(server)
    names = {t.name for t in await server.list_tools()}
    assert not any(name.startswith("client_") for name in names)
    assert "planner_export_report" not in names
