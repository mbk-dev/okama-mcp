"""MCP has no SQL layer; persistent access modes gate every Planner operation."""

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
        assert {"client_data_mode_get", "client_data_mode_set", "client_create"} <= names
        for name, arguments in (
            ("client_create", {"details": {"full_name": "SYNTHETIC_PRIVATE_PERSON"}}),
            ("client_meeting_save", {"code": code, "meeting": {"goal": "PRIVATE"}}),
            ("client_history", {"code": code, "table": "client_registry"}),
        ):
            rejected = await client.call_tool_mcp(name, arguments)
            assert rejected.is_error
            assert "SYNTHETIC_PRIVATE_PERSON" not in rejected.model_dump_json()
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


@pytest.mark.asyncio
async def test_legacy_startup_flag_never_overrides_saved_revocation(tmp_path: Path) -> None:
    path = tmp_path / "clients.db"
    PlannerStore.initialize(path).close()
    first = FastMCP("bootstrap")
    clients.register(first, path, allow_personal_data=True)
    async with Client(first) as client:
        mode = await client.call_tool("client_data_mode_get", {})
        assert mode.data == {"mode": "personal_data"}
        await client.call_tool("client_data_mode_set", {"mode": "anonymous"})
    second = FastMCP("revoked")
    clients.register(second, path, allow_personal_data=True)
    async with Client(second) as client:
        mode = await client.call_tool("client_data_mode_get", {})
        assert mode.data == {"mode": "anonymous"}
        rejected = await client.call_tool_mcp("client_create", {"details": {"full_name": "Synthetic"}})
        assert rejected.is_error


@pytest.mark.asyncio
async def test_saved_mode_applies_to_meetings_and_history(tmp_path: Path) -> None:
    path = tmp_path / "clients.db"
    with PlannerStore.initialize(path) as store:
        code = store.create_client({"full_name": "Synthetic"})["code"]
    server = FastMCP("meetings")
    clients.register(server, path)
    async with Client(server) as client:
        await client.call_tool("client_data_mode_set", {"mode": "personal_data"})
        created = await client.call_tool("client_meeting_save", {"code": code, "meeting": {
            "goal": "PRIVATE_MEETING", "date": "2026-10-26", "format": "online", "notes": "PRIVATE_NOTE"}})
        meeting = created.data
        assert "PRIVATE_MEETING" in (await client.call_tool_mcp("client_meeting_list", {"code": code})).model_dump_json()
        history = await client.call_tool_mcp("client_history", {"code": code, "table": "client_registry"})
        assert not history.is_error
        await client.call_tool("client_data_mode_set", {"mode": "anonymous"})
        listed = await client.call_tool_mcp("client_meeting_list", {"code": code})
        assert not listed.is_error and "PRIVATE" not in listed.model_dump_json()
        for name, args in (("client_history", {"code": code, "table": "client_registry"}),
                           ("client_meeting_delete", {"code": code, "meeting_id": meeting["id"], "revision": meeting["revision"]})):
            rejected = await client.call_tool_mcp(name, args)
            assert rejected.is_error
        await client.call_tool("client_data_mode_set", {"mode": "personal_data"})
        stale = await client.call_tool_mcp("client_meeting_delete", {"code": code, "meeting_id": meeting["id"], "revision": "stale"})
        assert stale.is_error
        deleted = await client.call_tool_mcp("client_meeting_delete", {"code": code, "meeting_id": meeting["id"], "revision": meeting["revision"]})
        assert not deleted.is_error
