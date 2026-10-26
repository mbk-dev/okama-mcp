"""MCP has no SQL layer; access mode is a local startup setting enforced by Planner."""

import ast
import json
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from okama_planner.storage import PlannerStore
from okama_mcp.tools import clients


@pytest.mark.asyncio
async def test_default_mode_is_anonymous_and_read_only(tmp_path: Path) -> None:
    path = tmp_path / "clients.db"
    with PlannerStore.initialize(path) as store:
        code = store.create_client({"full_name": "SYNTHETIC_PRIVATE_PERSON", "crm_id": "CRM-0001"})["code"]
    server = FastMCP("anonymous")
    clients.register(server, path)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert (
            not {
                "client_create",
                "client_update",
                "client_delete",
                "client_save_plan",
                "client_set_tax_residency",
                "client_meeting_save",
                "client_meeting_delete",
            }
            & names
        )
        response = await client.call_tool_mcp("client_get", {"code": code})
        assert not response.is_error
        assert "SYNTHETIC_PRIVATE_PERSON" not in response.model_dump_json()
        assert "CRM-0001" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_opt_in_full_crud_uses_planner_and_can_be_switched_off(tmp_path: Path) -> None:
    path = tmp_path / "clients.db"
    PlannerStore.initialize(path).close()
    server = FastMCP("personal")
    try:
        clients.register(server, path, allow_personal_data=True)
    except TypeError:
        pytest.fail("MCP needs an explicit local personal-data switch")
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {
            "client_create",
            "client_delete",
            "client_update",
            "client_history",
            "client_meeting_list",
            "client_meeting_save",
            "client_meeting_delete",
        } <= names
        response = await client.call_tool_mcp(
            "client_create", {"details": {"full_name": "SYNTHETIC_PRIVATE_PERSON", "crm_id": "CRM-001"}}
        )
        assert not response.is_error, response.content
        created = json.loads(response.content[0].text)
        code = created["code"]
        assert created["full_name"] == "SYNTHETIC_PRIVATE_PERSON"
        response = await client.call_tool_mcp("client_update", {"code": code, "changes": {"crm_id": "CRM-002"}})
        assert not response.is_error and "CRM-002" in response.model_dump_json()
        response = await client.call_tool_mcp("client_delete", {"code": code})
        assert not response.is_error
    with PlannerStore.open(path) as store:
        assert store.list_clients() == []


def test_no_direct_database_imports_in_mcp() -> None:
    for path in (Path(__file__).parents[1] / "src/okama_mcp").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [entry.name for entry in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name.split(".")[0] in {"sqlite3", "sqlalchemy", "alembic"} for name in names), path
