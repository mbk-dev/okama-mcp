"""Local configuration cannot be enabled on the public HTTP command."""
from pathlib import Path
import pytest


def test_local_options_are_stdio_only() -> None:
    from okama_mcp.transport import build_parser
    parser = build_parser()
    args = parser.parse_args(["stdio", "--client-db", "/synthetic/db.sqlite3"])
    assert args.client_db == Path("/synthetic/db.sqlite3")
    for option in ("--client-db", "--reports-dir", "--report-brand"):
        with pytest.raises(SystemExit):
            parser.parse_args(["http", option, "/synthetic/path"])


def test_initialize_command_is_explicit(tmp_path: Path) -> None:
    from okama_mcp.transport import main
    from okama_planner.storage import PlannerStore
    path = tmp_path / "new.sqlite3"
    assert main(["init-client-db", "--path", str(path)]) == 0
    with PlannerStore.open(path) as store:
        assert store.list_clients() == []
    with pytest.raises(FileExistsError):
        main(["init-client-db", "--path", str(path)])


def test_transport_invocations_do_not_share_local_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from fastmcp import FastMCP
    from okama_planner.storage import PlannerStore
    from okama_mcp.transport import main
    path = tmp_path / "isolated.sqlite3"
    with PlannerStore.initialize(path):
        pass
    servers = []
    monkeypatch.setattr(FastMCP, "run", lambda self, **kwargs: servers.append(self))
    main(["stdio", "--client-db", str(path)])
    main(["http"])
    assert servers[0] is not servers[1]
    names = {t.name for t in asyncio.run(servers[1].list_tools())}
    assert not any(name.startswith("client_") for name in names)
