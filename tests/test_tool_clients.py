"""Actual MCP registry behavior against synthetic Planner databases."""
import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP


def response_data(response: object) -> dict:
    if not response.content:
        return response.structured_content["result"]
    return json.loads(response.content[0].text)


def registry(tmp_path: Path) -> tuple[FastMCP, Path]:
    from okama_planner.storage import PlannerStore
    from okama_mcp.tools import clients

    path = tmp_path / "clients.sqlite3"
    with PlannerStore.initialize(path):
        pass
    server = FastMCP("local-clients")
    clients.register(server, path)
    return server, path


@pytest.mark.asyncio
async def test_create_update_residency_and_restart(tmp_path: Path) -> None:
    server, path = registry(tmp_path)
    async with Client(server) as client:
        names = {t.name for t in await client.list_tools()}
        assert names == {"client_create", "client_get", "client_list", "client_update",
                         "client_set_tax_residency", "client_get_tax_residency"}
        created = response_data(await client.call_tool_mcp("client_create", {
            "details": {"full_name": "Synthetic Person", "brokers": []}, "request_id": "creation-1"}))
        code = created["client"]["code"]
        assert created["status"] == "created"
        assert created["client"]["brokers"] == []
        updated = response_data(await client.call_tool_mcp("client_update", {
            "code": code, "changes": {"email": "fiction@example.invalid", "primary_channel": "email"}}))
        assert updated["primary_channel"] == "email"
        invalid = await client.call_tool_mcp("client_update", {"code": code, "changes": {"email": None}})
        assert invalid.model_dump(by_alias=True)["isError"]
        for country in ("ru", "DE", "DE"):
            residency = response_data(await client.call_tool_mcp("client_set_tax_residency", {
                "code": code, "residency": {"year": 2026, "country": country}}))
            assert residency["country"] == country.upper()
    from okama_mcp.tools import clients
    restarted = FastMCP("restarted")
    clients.register(restarted, path)
    async with Client(restarted) as client:
        saved = response_data(await client.call_tool_mcp("client_get", {"code": code}))
        assert saved["email"] == "fiction@example.invalid"
        assert saved["brokers"] == []
        replay = response_data(await client.call_tool_mcp("client_create", {
            "details": {"full_name": "Synthetic Person", "brokers": []}, "request_id": "creation-1"}))
        assert replay["status"] == "replayed"
        assert replay["client"]["code"] == code
        assert response_data(await client.call_tool_mcp("client_get_tax_residency", {
            "code": code, "year": 2026}))["country"] == "DE"
        assert response_data(await client.call_tool_mcp("client_get_tax_residency", {
            "code": code, "year": 2025})) is None


@pytest.mark.asyncio
async def test_duplicate_retry_and_unknown_fields(tmp_path: Path) -> None:
    server, _ = registry(tmp_path)
    args = {"details": {"full_name": "Synthetic Person"}, "request_id": "first"}
    async with Client(server) as client:
        original = response_data(await client.call_tool_mcp("client_create", args))
        assert original["client"]["brokers"] is None
        duplicate = response_data(await client.call_tool_mcp("client_create", args | {"request_id": "second"}))
        assert duplicate["status"] == "duplicate"
        assert duplicate["candidates"][0]["code"] == original["client"]["code"]
        namesake = response_data(await client.call_tool_mcp("client_create", args | {
            "request_id": "second", "allow_duplicate": True}))
        assert namesake["client"]["code"] != original["client"]["code"]
        for details in ({"full_name": "Changed"}, {"full_name": "Synthetic Person", "unknown": 1}):
            response = await client.call_tool_mcp("client_create", args | {"details": details})
            assert response.model_dump(by_alias=True)["isError"]
        rows = response_data(await client.call_tool_mcp("client_list", {}))
        assert len(rows) == 2
        invalid = await client.call_tool_mcp("client_update", {
            "code": original["client"]["code"], "changes": {"unknown": "bad"}})
        assert invalid.model_dump(by_alias=True)["isError"]


@pytest.mark.asyncio
async def test_concurrent_retry_creates_once(tmp_path: Path) -> None:
    server, _ = registry(tmp_path)
    async with Client(server) as client:
        responses = await asyncio.gather(*[client.call_tool_mcp("client_create", {
            "details": {"full_name": "Synthetic Race"}, "request_id": "same"}) for _ in range(4)])
        assert all(not r.model_dump(by_alias=True)["isError"] for r in responses)
        assert len({response_data(r)["client"]["code"] for r in responses}) == 1
        assert len(response_data(await client.call_tool_mcp("client_list", {}))) == 1


def test_interrupted_receipt_never_recreates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from okama_mcp.local_registry import create_client
    from okama_planner.storage import PlannerStore

    _, path = registry(tmp_path)
    original = PlannerStore.create_client

    def interrupted(self: object, details: dict) -> dict:
        original(self, details)
        raise RuntimeError("lost response after commit")

    monkeypatch.setattr(PlannerStore, "create_client", interrupted)
    with pytest.raises(RuntimeError, match="lost response"):
        create_client(path, {"full_name": "Synthetic Interrupted"}, "interrupted", False)
    monkeypatch.setattr(PlannerStore, "create_client", original)
    with pytest.raises(ValueError, match="pending"):
        create_client(path, {"full_name": "Synthetic Interrupted"}, "interrupted", False)
    with PlannerStore.open(path) as store:
        assert len(store.list_clients()) == 1


def test_registry_does_not_create_missing_database(tmp_path: Path) -> None:
    from okama_mcp.tools import clients
    with pytest.raises(FileNotFoundError):
        clients.register(FastMCP("missing"), tmp_path / "missing.sqlite3")


def test_synthetic_stdio_example_verifies_restart_and_reports() -> None:
    import subprocess
    import sys
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "examples/local_planner_client.py")],
                            cwd=root, capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stderr
    assert "verified restart, retry, duplicate, unknown field, empty brokers, residency, forecast, report" in result.stdout


@pytest.mark.parametrize("shared_id", [True, False])
def test_separate_process_creators_preserve_single_record(tmp_path: Path, shared_id: bool) -> None:
    import subprocess
    import sys
    from okama_planner.storage import PlannerStore
    _, path = registry(tmp_path)
    script = (
        "import json,sys; from pathlib import Path; from okama_mcp.local_registry import create_client; "
        "print(json.dumps(create_client(Path(sys.argv[1]), {'full_name':'Synthetic Processes'}, sys.argv[2])))"
    )
    processes = [subprocess.Popen([sys.executable, "-c", script, str(path),
                                   "shared" if shared_id else f"request-{i}"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for i in range(2)]
    statuses = []
    for process in processes:
        output, error = process.communicate(timeout=30)
        assert process.returncode == 0, error
        statuses.append(json.loads(output)["status"])
    assert set(statuses) == {"created", "replayed" if shared_id else "duplicate"}
    with PlannerStore.open(path) as store:
        assert len(store.list_clients()) == 1
