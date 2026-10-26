"""Persistent MCP access modes, exercised only against synthetic Planner databases."""
import json
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP

from okama_mcp.tools import clients

MARKER = "PRIVATE_SYNTHETIC_IDENTITY"


def server_for(path: Path) -> FastMCP:
    server = FastMCP("client-modes")
    clients.register(server, path)
    return server


@pytest.fixture
def database(tmp_path: Path) -> tuple[Path, str]:
    from okama_planner.storage import PlannerStore
    path = tmp_path / "clients.sqlite3"
    with PlannerStore.initialize(path) as store:
        record = store.create_client({"full_name": MARKER, "email": "private@example.invalid"})
    return path, record["code"]


async def call(client: Client, name: str, arguments: dict | None = None) -> object:
    result = await client.call_tool_mcp(name, arguments or {})
    assert not result.is_error, result.content
    return json.loads(result.content[0].text) if result.content else result.structured_content["result"]


@pytest.mark.asyncio
async def test_mode_defaults_to_anonymous_and_persists_across_servers(database: tuple[Path, str]) -> None:
    path, code = database
    # Register the second connection before switching to expose stale in-memory settings.
    first, second = server_for(path), server_for(path)
    async with Client(first) as one, Client(second) as two:
        assert (await call(one, "client_data_mode_get"))["mode"] == "anonymous"
        assert MARKER not in json.dumps(await call(one, "client_get", {"code": code}))
        assert (await call(one, "client_data_mode_set", {"mode": "personal_data"}))["mode"] == "personal_data"
        assert (await call(two, "client_get", {"code": code}))["full_name"] == MARKER
    async with Client(server_for(path)) as restarted:
        assert (await call(restarted, "client_data_mode_get"))["mode"] == "personal_data"
        await call(restarted, "client_data_mode_set", {"mode": "anonymous"})
    async with Client(first) as one:
        assert MARKER not in json.dumps(await call(one, "client_list"))
        assert (await call(one, "client_data_mode_get"))["mode"] == "anonymous"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,arguments", [
    ("client_create", {"details": {"full_name": MARKER}}),
    ("client_update", {"changes": {"birth_year": 1980}}),
    ("client_update", {"changes": {"email": "changed@example.invalid"}}),
    ("client_delete", {}),
    ("client_set_tax_residency", {"residency": {"year": 2026, "country": "DE", "note": MARKER}}),
    ("client_save_plan", {"request": "fixture"}),
])
async def test_anonymous_mutations_are_rejected_without_changes(
    database: tuple[Path, str], name: str, arguments: dict,
) -> None:
    from okama_planner.storage import PlannerStore
    path, code = database
    arguments = dict(arguments)
    if name != "client_create":
        arguments["code"] = code
    if name == "client_save_plan":
        arguments["request"] = json.loads(Path("examples/planner/modes-single-request.json").read_text())
    before = path.read_bytes()
    async with Client(server_for(path)) as client:
        response = await client.call_tool_mcp(name, arguments)
        assert response.is_error
        assert "personal" in response.content[0].text.lower()
        assert MARKER not in response.model_dump_json()
    assert path.read_bytes() == before
    with PlannerStore.open(path) as store:
        assert len(store.list_clients()) == 1
        assert store.get_client(code)["birth_year"] is None


@pytest.mark.asyncio
async def test_personal_crud_preserves_sparse_fields_and_isolates_deletion(database: tuple[Path, str]) -> None:
    from okama_planner.storage import PlannerStore
    path, original = database
    async with Client(server_for(path)) as client:
        await call(client, "client_data_mode_set", {"mode": "personal_data"})
        created = await call(client, "client_create", {"details": {
            "full_name": "Second synthetic person", "email": "second@example.invalid", "note": MARKER}})
        code = created["code"]
        updated = await call(client, "client_update", {"code": code, "changes": {"phone": "+123456789"}})
        assert updated["email"] == "second@example.invalid"
        assert updated["full_name"] == created["full_name"]
        cleared = await call(client, "client_update", {"code": code, "changes": {"phone": None}})
        assert cleared["phone"] is None
        assert len(await call(client, "client_list")) == 2
        await call(client, "client_set_tax_residency", {"code": code, "residency": {
            "year": 2026, "country": "de", "note": MARKER}})
        residency = await call(client, "client_get_tax_residency", {"code": code, "year": 2026})
        assert residency["note"] == MARKER
        request = json.loads(Path("examples/planner/modes-single-request.json").read_text())
        request["plan"]["assets"][0]["label"] = MARKER
        saved = await call(client, "client_save_plan", {"code": code, "request": request})
        assert MARKER in json.dumps(await call(client, "client_load_plan", saved))
        assert MARKER not in json.dumps(await call(client, "client_forecast", saved))
        await call(client, "client_data_mode_set", {"mode": "anonymous"})
        assert MARKER not in json.dumps(await call(client, "client_load_plan", saved))
        assert MARKER not in json.dumps(await call(client, "client_get_tax_residency", {"code": code, "year": 2026}))
        await call(client, "client_data_mode_set", {"mode": "personal_data"})
        assert await call(client, "client_delete", {"code": code}) == {"code": code, "deleted": True}
        assert [row["code"] for row in await call(client, "client_list")] == [original]
    with PlannerStore.open(path) as store:
        assert store.get_client(original)["full_name"] == MARKER
        with pytest.raises(LookupError):
            store.get_client(code)
        with pytest.raises(LookupError):
            store.list_plans(code)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, True, 1, "personal", MARKER])
async def test_invalid_switch_does_not_change_mode_or_leak(
    database: tuple[Path, str], mode: object, caplog: pytest.LogCaptureFixture,
) -> None:
    path, _ = database
    async with Client(server_for(path)) as client:
        response = await client.call_tool_mcp("client_data_mode_set", {"mode": mode})
        assert response.is_error
        assert MARKER not in response.model_dump_json() + caplog.text
        assert (await call(client, "client_data_mode_get"))["mode"] == "anonymous"


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "ru", "de", "es", "zh"])
async def test_personal_validation_and_runtime_errors_stay_sanitized(
    database: tuple[Path, str], language: str, caplog: pytest.LogCaptureFixture,
) -> None:
    path, code = database
    async with Client(server_for(path)) as client:
        await call(client, "client_data_mode_set", {"mode": "personal_data"})
        for name, arguments in (("client_get", {"code": code}), ("client_list", {})):
            response = await call(client, name, {**arguments, "language": language})
            assert MARKER in json.dumps(response)
        for name, arguments in [
            ("client_create", {"details": {"full_name": MARKER, "unexpected": MARKER}}),
            ("client_update", {"code": code, "changes": {"full_name": None, "note": MARKER}}),
            ("client_delete", {"code": MARKER}),
        ]:
            response = await client.call_tool_mcp(name, {**arguments, "language": language})
            assert response.is_error
            assert MARKER not in response.model_dump_json() + caplog.text


@pytest.mark.asyncio
async def test_mode_is_scoped_to_database_and_corrupt_settings_fail_closed(
    database: tuple[Path, str], tmp_path: Path,
) -> None:
    from okama_planner.storage import PlannerStore
    path, code = database
    other = tmp_path / "other.sqlite3"
    with PlannerStore.initialize(other):
        pass
    async with Client(server_for(path)) as client, Client(server_for(other)) as separate:
        await call(client, "client_data_mode_set", {"mode": "personal_data"})
        assert (await call(separate, "client_data_mode_get"))["mode"] == "anonymous"
        settings = path.with_name(path.name + ".mcp-access.json")
        assert settings.stat().st_mode & 0o777 == 0o600
        assert MARKER not in settings.read_text()
        settings.write_text('{"mode": "personal_data", "unexpected": true}')
        rejected = await client.call_tool_mcp("client_get", {"code": code})
        assert rejected.is_error
        assert MARKER not in rejected.model_dump_json()
        await call(client, "client_data_mode_set", {"mode": "anonymous"})
        assert MARKER not in json.dumps(await call(client, "client_get", {"code": code}))


@pytest.mark.asyncio
@pytest.mark.parametrize("initial,target", [("anonymous", "personal_data"), ("personal_data", "anonymous")])
async def test_failed_policy_write_keeps_previous_mode(
    database: tuple[Path, str], initial: str, target: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _ = database
    async with Client(server_for(path)) as client:
        await call(client, "client_data_mode_set", {"mode": initial})

        def fail_replace(source: Path, destination: Path) -> None:
            raise PermissionError(MARKER)

        monkeypatch.setattr(Path, "replace", fail_replace)
        response = await client.call_tool_mcp("client_data_mode_set", {"mode": target})
        assert response.is_error
        assert MARKER not in response.model_dump_json()
        assert (await call(client, "client_data_mode_get"))["mode"] == initial
        assert not list(path.parent.glob(".clients.sqlite3.mcp-access.json.*"))


def test_old_companion_cannot_expose_client_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import ModuleType

    monkeypatch.setitem(sys.modules, "okama_planner.ai", ModuleType("okama_planner.ai"))
    with pytest.raises(ImportError):
        clients.register(FastMCP("old-client-companion"), tmp_path / "missing.sqlite3")


@pytest.mark.asyncio
async def test_residency_update_preserves_omitted_note_and_allows_explicit_clear(database: tuple[Path, str]) -> None:
    path, code = database
    async with Client(server_for(path)) as client:
        await call(client, "client_data_mode_set", {"mode": "personal_data"})
        await call(client, "client_set_tax_residency", {"code": code, "residency": {
            "year": 2026, "country": "DE", "note": MARKER}})
        updated = await call(client, "client_set_tax_residency", {"code": code, "residency": {
            "year": 2026, "country": "US"}})
        assert updated["note"] == MARKER
        assert updated["country"] == "US"
        cleared = await call(client, "client_set_tax_residency", {"code": code, "residency": {
            "year": 2026, "country": "US", "note": None}})
        assert cleared["note"] is None
