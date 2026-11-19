import asyncio
import json
from collections.abc import Awaitable, Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import sys
import tomllib
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def probe_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "docs/research/codex-lazy-stdio/probe.py"
    spec = spec_from_file_location("research_stdio_probe", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_helper_uses_paths_with_spaces(
    probe_module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout = tmp_path / "research checkout"
    monkeypatch.setattr(probe_module, "__file__", str(checkout / "docs/research/codex-lazy-stdio/probe.py"))
    helper = checkout / ".venv/bin/okama-mcp"
    helper.parent.mkdir(parents=True)
    helper.symlink_to(sys.executable)
    (checkout / "stdio").write_text('print("synthetic stdio helper")\n', encoding="utf-8")
    output = tmp_path / "probe output"

    async def stop_before_launch(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic app-server launch failure")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", stop_before_launch)
    with pytest.raises(RuntimeError, match="synthetic app-server launch failure"):
        await probe_module.probe("lazy", output)

    with (output / "home/config.toml").open("rb") as config:
        server = tomllib.load(config)["mcp_servers"]["okama"]
    assert server["cwd"] == str(checkout)
    assert server["command"] == sys.executable
    result = subprocess.run(
        [server["command"], *server["args"]],
        cwd=server["cwd"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert result.stdout == "synthetic stdio helper\n"
    pid, timestamp = (output / "pids").read_text().strip().split()
    assert int(pid) > 0
    seconds, nanoseconds = timestamp.split(".")
    assert int(seconds) > 0 and len(nanoseconds) == 9 and nanoseconds.isdecimal()


def assert_shutdown_evidence(
    output: Path, expected_pid: int | None, expected_alive: bool | None, read_error: tuple[str, type[OSError]] | None
) -> None:
    events = [json.loads(line)["message"] for line in (output / "events.jsonl").read_text().splitlines()]
    assert events[0]["result"] == {}
    assert events[-1] == {"method": "synthetic/stopped"}
    snapshot = json.loads((output / "snapshots.jsonl").read_text().splitlines()[-1])
    assert snapshot["label"] == "app-server-exit"
    assert [row["pid"] for row in snapshot["servers"]] == ([] if expected_pid is None else [expected_pid])
    if expected_pid is not None:
        (helper,) = snapshot["servers"]
        assert helper["alive"] is expected_alive
        if read_error:
            filename, error_type = read_error
            assert helper["inspection_error"] == f"{error_type.__name__}: synthetic read error for {filename}"


def fake_proc(
    proc: Path, state: str | None, read_error: tuple[str, type[OSError]] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    if state is None:
        return
    proc.mkdir(parents=True)
    (proc / "stat").write_text(f"{proc.name} (synthetic (Python) helper) {state}\n")
    (proc / "cmdline").write_text("synthetic-helper\x00")
    (proc / "status").write_text("Name: synthetic-helper\n")
    (proc / "smaps_rollup").write_text("Rss: 4 kB\n")
    if read_error:
        filename, error_type = read_error
        read_text = Path.read_text

        def read_proc(path: Path, *args: Any, **kwargs: Any) -> str:
            if path == proc / filename:
                raise error_type(f"synthetic read error for {filename}")
            return read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read_proc)


def expire_rpc_future(monkeypatch: pytest.MonkeyPatch, on_timeout: Callable[[], None] | None) -> None:
    wait_for = asyncio.wait_for

    async def time_out_rpc(awaitable: Awaitable[Any], timeout: float) -> Any:
        if isinstance(awaitable, asyncio.Future) and not isinstance(awaitable, asyncio.Task):
            try:
                return await wait_for(awaitable, 0)
            except TimeoutError:
                if on_timeout is not None:
                    on_timeout()
                    await asyncio.sleep(0)
                raise
        return await wait_for(awaitable, timeout)

    monkeypatch.setattr(asyncio, "wait_for", time_out_rpc)


@pytest.mark.parametrize(
    ("helper_state", "read_error", "reply_during_timeout", "expected_alive"),
    [
        (None, None, False, False),
        (None, None, True, False),
        ("S", None, False, True),
        ("Z", None, False, False),
        ("S", ("smaps_rollup", PermissionError), False, True),
        ("S", ("smaps_rollup", FileNotFoundError), False, True),
        ("S", ("stat", PermissionError), False, None),
    ],
    ids=[
        "late-reply",
        "cancelled-future",
        "surviving-helper",
        "zombie-helper",
        "unreadable-memory-details",
        "missing-memory-details",
        "unknown-state",
    ],
)
async def test_late_reply_keeps_shutdown_evidence(
    probe_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    helper_state: str | None,
    read_error: tuple[str, type[OSError]] | None,
    reply_during_timeout: bool,
    expected_alive: bool | None,
) -> None:
    output = tmp_path / "probe"
    stdout = asyncio.StreamReader()
    stdin = Mock(drain=AsyncMock())
    proc_dir = tmp_path / "synthetic proc"
    helper_pid = 12345
    stderr = None

    fake_proc(proc_dir / str(helper_pid), helper_state, read_error, monkeypatch)

    def path_for_probe(path: str) -> Path:
        return proc_dir if path == "/proc" else Path(path)

    def feed_reply() -> None:
        request = json.loads(stdin.write.call_args.args[0])
        stdout.feed_data((json.dumps({"id": request["id"], "result": {}}) + "\n").encode())

    async def wait() -> int:
        if not reply_during_timeout:
            feed_reply()
        stdout.feed_data(b'{"method":"synthetic/stopped"}\n')
        stdout.feed_eof()
        return 0

    async def launch(*args: Any, **kwargs: Any) -> SimpleNamespace:
        nonlocal stderr
        stderr = kwargs["stderr"]
        if helper_state is not None:
            (output / "pids").write_text(f"{helper_pid} 1.000000000\n")
        return SimpleNamespace(pid=12344, stdin=stdin, stdout=stdout, wait=wait)

    monkeypatch.setattr(probe_module, "Path", path_for_probe)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    expire_rpc_future(monkeypatch, feed_reply if reply_during_timeout else None)

    if expected_alive is not False:
        with pytest.raises(RuntimeError, match=f"app-server-exit.*{helper_pid}") as error:
            await probe_module.probe("lazy", output)
        assert isinstance(error.value.__context__, TimeoutError)
    else:
        with pytest.raises(TimeoutError):
            await probe_module.probe("lazy", output)

    stdin.close.assert_called_once_with()
    assert stderr is not None and stderr.closed
    assert_shutdown_evidence(output, helper_pid if helper_state is not None else None, expected_alive, read_error)
