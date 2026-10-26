"""Acceptance of installed distributions over real stdio, using synthetic data only.

Run with an isolated interpreter (-I); no editable packages or source path overrides.
The same probe is used before publishing a wheel and after installing from PyPI.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import importlib
import json
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from openpyxl import load_workbook
from okama_planner.storage import PlannerStore

MARKER = "PRIVATE_SYNTHETIC_RELEASE_MARKER"


def data(response: Any) -> Any:
    assert not response.is_error, response.content
    serialized = response.model_dump_json()
    assert MARKER not in serialized
    return json.loads(response.content[0].text)


async def acceptance(fixtures: Path, output: Path, live: bool = False) -> None:
    output.mkdir(parents=True, exist_ok=False)
    installed = {}
    for name in ("okama_mcp", "okama_planner", "okama_planner.ai", "okama"):
        module_path = Path(importlib.import_module(name).__file__).resolve()
        assert module_path.is_relative_to(Path(sys.prefix).resolve()), module_path
        installed[name] = str(module_path)
    versions = {name: version(name) for name in ("okama-mcp", "okama-planner", "okama", "fastmcp")}
    database = output / "synthetic.sqlite3"
    reports = output / "reports"
    reports.mkdir()
    request = json.loads((fixtures / "modes-single-request.json").read_text())
    variant = json.loads((fixtures / "modes-per_goal-request.json").read_text())
    request["plan"]["assets"][0]["label"] = MARKER
    with PlannerStore.initialize(database) as store:
        code = store.create_client({"full_name": MARKER, "email": f"{MARKER}@example.invalid"})["code"]
        store.save_plan(code, request)
    command = ["-I", "-m", "okama_mcp.transport", "stdio", "--client-db", str(database),
               "--reports-dir", str(reports)]
    transport = StdioTransport(command=sys.executable, args=command, cwd=str(output),
                               log_file=output / "server.log")
    async with Client(transport) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {"planner_forecast", "planner_compare_modes", "client_list", "client_load_plan",
                "client_forecast", "planner_export_report", "finplan_forecast", "finplan_backtest"} <= names
        assert len(names) == 70, sorted(names)
        forecast = data(await client.call_tool_mcp("planner_forecast", {"request": request}))
        assert "privacy_proof" in forecast
        comparison = data(await client.call_tool_mcp("planner_compare_modes", {
            "baseline": request, "variant": variant}))
        assert {"baseline", "variant"} <= comparison.keys()
        assert "privacy_proof" in comparison["baseline"]
        assert code in json.dumps(data(await client.call_tool_mcp("client_list", {})))
        assert {"client_create", "client_delete", "client_update", "client_save_plan",
                "client_data_mode_get", "client_data_mode_set"} <= names
        assert data(await client.call_tool_mcp("client_data_mode_get", {})) == {"mode": "anonymous"}
        denied = await client.call_tool_mcp("client_update", {"code": code, "changes": {"crm_id": "DENIED"}})
        assert denied.is_error
        saved = {"code": code, "version": 1}
        data(await client.call_tool_mcp("client_load_plan", saved))
        local = data(await client.call_tool_mcp("client_forecast", saved))
        assert local["metrics"] == forecast["metrics"]
        scenario = {"label": MARKER, "request": request, "result": forecast}
        report = data(await client.call_tool_mcp("planner_export_report", {"report": {
            "filename": "anonymous.xlsx", "scenarios": [scenario]}}))
        workbook = reports / report["filename"]
        book = load_workbook(workbook)
        try:
            assert MARKER not in str([list(sheet.values) for sheet in book])
        finally:
            book.close()
        for mode in ("unsigned", "tampered"):
            bad = copy.deepcopy(scenario)
            if mode == "unsigned":
                del bad["result"]["privacy_proof"]
            else:
                bad["result"]["metrics"]["terminal_p50"] += 1
            rejected = await client.call_tool_mcp("planner_export_report", {"report": {
                "filename": f"{mode}.xlsx", "scenarios": [bad]}})
            assert rejected.is_error
            assert MARKER not in rejected.model_dump_json()
        assert len(list(reports.iterdir())) == 1
        rejected = await client.call_tool_mcp("planner_forecast", {"request": {"private": MARKER}})
        assert rejected.is_error and MARKER not in rejected.model_dump_json()
        if live:
            portfolio = {"assets": ["SPY.US", "GLD.US"], "weights": [0.6, 0.4], "ccy": "USD",
                         "first_date": "2015-01", "last_date": "2020-12", "inflation": False}
            plan = {"stages": [{"portfolio": portfolio, "period_years": 1,
                    "cashflow": {"type": "indexation", "initial_investment": 1000,
                                 "frequency": "year", "amount": 10, "indexation": 0}}],
                    "scenarios": 20, "random_seed": 42, "discount_rate": 0}
            core = data(await client.call_tool_mcp("finplan_forecast", {"plan": plan}))
            assert core["plan_spec"]["scenarios"] == 20
        assert data(await client.call_tool_mcp("client_data_mode_set", {"mode": "personal_data"})) == {
            "mode": "personal_data"}
    personal_transport = StdioTransport(command=sys.executable, args=command,
                                       cwd=str(output), log_file=output / "personal-server.log")
    async with Client(personal_transport) as client:
        personal_names = {tool.name for tool in await client.list_tools()}
        assert len(personal_names) == 70
        assert data(await client.call_tool_mcp("client_data_mode_get", {})) == {"mode": "personal_data"}
        visible = await client.call_tool_mcp("client_get", {"code": code})
        assert not visible.is_error and MARKER in visible.model_dump_json()
        created = await client.call_tool_mcp("client_create", {"details": {"full_name": "Synthetic CRUD"}})
        assert not created.is_error
        new_code = json.loads(created.content[0].text)["code"]
        changed = await client.call_tool_mcp("client_update", {"code": new_code, "changes": {"crm_id": "CRM-007"}})
        assert not changed.is_error and "CRM-007" in changed.model_dump_json()
        meeting = await client.call_tool_mcp("client_meeting_save", {"code": new_code, "meeting": {
            "goal": "Synthetic review", "date": "2026-10-26", "format": "online", "notes": "Synthetic notes"}})
        assert not meeting.is_error
        row = json.loads(meeting.content[0].text)
        removed = await client.call_tool_mcp("client_meeting_delete", {
            "code": new_code, "meeting_id": row["id"], "revision": row["revision"]})
        assert not removed.is_error
        removed = await client.call_tool_mcp("client_delete", {"code": new_code})
        assert not removed.is_error
        assert data(await client.call_tool_mcp("client_data_mode_set", {"mode": "anonymous"})) == {
            "mode": "anonymous"}
        data(await client.call_tool_mcp("client_get", {"code": code}))
        denied = await client.call_tool_mcp("client_delete", {"code": code})
        assert denied.is_error
    public_transport = StdioTransport(command=sys.executable, args=["-I", "-m", "okama_mcp.transport", "stdio"],
                                     cwd=str(output), log_file=output / "public-server.log")
    async with Client(public_transport) as client:
        public_names = {tool.name for tool in await client.list_tools()}
        assert len(public_names) == 52
        assert "planner_forecast" in public_names and "planner_compare_modes" in public_names
        assert "client_list" not in public_names and "planner_export_report" not in public_names
    receipt = {"versions": versions, "installed_modules": installed, "tool_count": len(names),
               "forecast_metrics": forecast["metrics"], "anonymous_report": workbook.name,
               "privacy_rejections": ["unsigned", "tampered", "invalid_request"],
               "public_tool_count": len(public_names), "personal_tool_count": len(personal_names), "live_finplan": live, "status": "PASS"}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Also exercise finplan_forecast with public market data")
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(acceptance(args.fixtures.resolve(), args.output.resolve(), args.live), timeout=180))
