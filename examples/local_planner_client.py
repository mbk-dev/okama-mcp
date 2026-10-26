"""Exercise persistent client-data modes through real stdio with synthetic data."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def call(client: Client, name: str, arguments: dict[str, Any]) -> Any:
    response = await client.call_tool_mcp(name, arguments)
    assert not response.is_error, response.content
    return json.loads(response.content[0].text) if response.content else response.structured_content["result"]


async def main() -> None:
    from okama_planner.storage import PlannerStore
    root = Path(__file__).resolve().parents[1]
    output = root / "tmp" / "local-planner-demo" / uuid4().hex
    output.mkdir(parents=True)
    database = output / "synthetic.sqlite3"
    # This is synthetic local intake, outside the MCP transport.
    with PlannerStore.initialize(database) as store:
        code = store.create_client({"full_name": "PRIVATE_SYNTHETIC_PERSON",
                                    "email": "private@example.invalid"})["code"]

    def transport() -> StdioTransport:
        return StdioTransport(command=sys.executable, args=["-m", "okama_mcp.transport", "stdio",
                              "--client-db", str(database), "--reports-dir", str(output)],
                              cwd=str(root), env={"MPLBACKEND": "Agg", "PYTHONPATH": os.pathsep.join(filter(None, [
                                  str(root / "src"), os.environ.get("PYTHONPATH", "")]))}, keep_alive=False)

    async with Client(transport()) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {"client_create", "client_delete", "client_data_mode_get", "client_data_mode_set"} <= names
        assert await call(client, "client_data_mode_get", {}) == {"mode": "anonymous"}
        record = await call(client, "client_get", {"code": code})
        assert "PRIVATE_SYNTHETIC_PERSON" not in json.dumps(record)
        assert "private@example.invalid" not in json.dumps(record)
        rejected = await client.call_tool_mcp("client_update", {"code": code, "changes": {"email": "PRIVATE"}})
        assert rejected.is_error and "PRIVATE" not in rejected.model_dump_json()
        await call(client, "client_data_mode_set", {"mode": "personal_data"})
        assert (await call(client, "client_get", {"code": code}))["full_name"] == "PRIVATE_SYNTHETIC_PERSON"
        created = await call(client, "client_create", {"details": {"full_name": "SECOND_SYNTHETIC_PERSON"}})
        await call(client, "client_update", {"code": code, "changes": {"birth_year": 1980}})
        await call(client, "client_set_tax_residency", {"code": code, "residency": {"year": 2026, "country": "DE"}})
        request = json.loads((root / "examples/planner/modes-single-request.json").read_text())
        saved = await call(client, "client_save_plan", {"code": code, "request": request})
        forecast = await call(client, "planner_forecast", {"request": request})
        artifact = await call(client, "planner_export_report", {"report": {"scenarios": [
            {"label": "Synthetic", "request": request, "result": forecast}], "filename": "synthetic.xlsx"}})
        assert (output / artifact["filename"]).is_file()
        assert str(output) not in json.dumps(artifact)
    async with Client(transport()) as client:
        assert await call(client, "client_data_mode_get", {}) == {"mode": "personal_data"}
        assert (await call(client, "client_get", {"code": code}))["birth_year"] == 1980
        assert await call(client, "client_list_plans", {"code": code}) == [saved]
        await call(client, "client_data_mode_set", {"mode": "anonymous"})
        assert "PRIVATE_SYNTHETIC_PERSON" not in json.dumps(await call(client, "client_get", {"code": code}))
        rejected = await client.call_tool_mcp("client_delete", {"code": created["code"]})
        assert rejected.is_error
    async with Client(transport()) as client:
        assert await call(client, "client_data_mode_get", {}) == {"mode": "anonymous"}
        await call(client, "client_data_mode_set", {"mode": "personal_data"})
        assert await call(client, "client_delete", {"code": created["code"]}) == {
            "code": created["code"], "deleted": True}
        await call(client, "client_data_mode_set", {"mode": "anonymous"})
    print(f"Verified {len(names)} tools: anonymity, blocked writes, personal CRUD, persistent modes, plans and reports")


if __name__ == "__main__":
    asyncio.run(main())
