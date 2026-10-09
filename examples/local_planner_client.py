"""Synthetic stdio acceptance from either an editable checkout or installed wheels."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def call(client: Client, name: str, arguments: dict[str, Any]) -> Any:
    response = await client.call_tool_mcp(name, arguments)
    if response.model_dump(by_alias=True)["isError"]:
        raise RuntimeError(f"{name}: {response.content}")
    if response.content:
        return json.loads(response.content[0].text)
    return response.structured_content["result"]


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "tmp" / "local-planner-demo" / uuid4().hex
    output.mkdir(parents=True)
    database = output / "synthetic.sqlite3"
    brand = output / "brand.json"
    brand.write_text(json.dumps({"company": "Synthetic Practice", "contact": "fiction@example.invalid"}))
    subprocess.run([sys.executable, "-m", "okama_mcp.transport", "init-client-db", "--path", str(database)],
                   cwd=root, check=True)
    subprocess.run([sys.executable, "-m", "okama_mcp.transport", "install-skill", "--destination",
                    str(output / ".agents/skills")], cwd=root, check=True)
    arguments = {"details": {"full_name": "Synthetic Person", "brokers": []}, "request_id": uuid4().hex}

    def transport(local: bool = True) -> StdioTransport:
        args = ["-m", "okama_mcp.transport", "stdio"]
        if local:
            args += ["--client-db", str(database), "--reports-dir", str(output), "--report-brand", str(brand)]
        return StdioTransport(command=sys.executable, args=args, cwd=str(root),
                              env={"MPLBACKEND": "Agg"}, keep_alive=False)

    async with Client(transport()) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        required = {"client_create", "client_get", "client_update", "client_list", "client_set_tax_residency",
                    "client_get_tax_residency", "planner_forecast", "planner_compare_modes", "planner_export_report"}
        assert required <= tools.keys()
        (output / "tools.json").write_text(json.dumps({name: tool.model_dump() for name, tool in tools.items()},
                                                     indent=2))
        created = await call(client, "client_create", arguments)
        assert created["status"] == "created"
        code = created["client"]["code"]
        assert created["client"]["brokers"] == []
        duplicate = await call(client, "client_create", arguments | {"request_id": uuid4().hex})
        assert duplicate["status"] == "duplicate"
        unknown = await client.call_tool_mcp("client_create", arguments | {
            "request_id": uuid4().hex, "details": {"full_name": "Invalid Synthetic", "unknown": "bad"}})
        assert unknown.model_dump(by_alias=True)["isError"]
        await call(client, "client_update", {"code": code, "changes": {
            "email": "fiction@example.invalid", "primary_channel": "email"}})
        await call(client, "client_set_tax_residency", {"code": code, "residency": {
            "year": 2026, "country": "DE"}})
        request = json.loads((root / "examples/planner/modes-single-request.json").read_text())
        forecast = await call(client, "planner_forecast", {"request": request})
        assert forecast["goals"][0]["p_funded"] == 1
        result = await call(client, "planner_export_report", {"report": {
            "scenarios": [{"label": "Synthetic", "request": request, "result": forecast}],
            "filename": "synthetic.xlsx", "language": "en"}})
        assert Path(result["path"]).is_file()
    # This starts a new OS process, reopening the existing database and creation receipts.
    async with Client(transport()) as client:
        replay = await call(client, "client_create", arguments)
        assert replay["status"] == "replayed" and replay["client"]["code"] == code
        assert replay["client"]["email"] == "fiction@example.invalid"
        assert replay["client"]["brokers"] == []
        assert len(await call(client, "client_list", {})) == 1
        assert (await call(client, "client_get_tax_residency", {"code": code, "year": 2026}))["country"] == "DE"
        assert await call(client, "client_get_tax_residency", {"code": code, "year": 2025}) is None
    async with Client(transport(False)) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert not any(name.startswith("client_") for name in names)
        assert "planner_export_report" not in names
    print("verified restart, retry, duplicate, unknown field, empty brokers, residency, forecast, report")
    print(f"Synthetic acceptance output: {output}")


if __name__ == "__main__":
    asyncio.run(main())
