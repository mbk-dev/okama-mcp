"""Bounded Codex 0.169.0 lifecycle probe; no model turns or global config writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any


async def probe(mode: str, output: Path) -> None:  # noqa: C901 - Keep the bounded diagnostic sequence together.
    """Run one fresh app-server with at most one live okama server at a time."""
    root = Path(__file__).resolve().parents[3]
    output.mkdir(parents=True, exist_ok=False)
    home = output / "home"
    home.mkdir()
    pid_log = output / "pids"
    wrapper = output / "server.sh"
    wrapper.write_text(
        f'#!/bin/sh\necho "$$ $(date +%s.%N)" >> "{pid_log}"\n'
        f'exec "{root}/.venv/bin/okama-mcp" stdio\n'
    )
    wrapper.chmod(0o700)
    required = mode in {"required", "required-catalog"}
    lazy = mode != "eager"
    readiness = "catalog" if mode == "required-catalog" else "connection"
    (home / "config.toml").write_text(
        f'thread_unload_delay_secs = 0\n[features]\n'
        f'mcp_lazy_stdio_startup = {str(lazy).lower()}\n'
        f'mcp_connection_sharing = false\n[mcp_servers.okama]\n'
        f'command = "{wrapper}"\ncwd = "{root}"\nstartup_timeout_sec = 60\n'
        f'required = {str(required).lower()}\nstartup_readiness = "{readiness}"\n'
    )
    events = (output / "events.jsonl").open("w")
    stderr = (output / "stderr.log").open("w")
    process = await asyncio.create_subprocess_exec(
        "codex", "app-server", "--stdio", cwd=output,
        env=dict(os.environ, CODEX_HOME=str(home)),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=stderr, limit=4 * 1024 * 1024,
    )
    assert process.stdin is not None and process.stdout is not None
    pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

    async def read() -> None:
        assert process.stdout is not None
        async for line in process.stdout:
            message = json.loads(line)
            events.write(json.dumps({"at": time.time(), "message": message}) + "\n")
            events.flush()
            if message.get("id") in pending:
                pending.pop(message["id"]).set_result(message)

    reader = asyncio.create_task(read())
    counter = 0

    async def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
        nonlocal counter
        counter += 1
        future = asyncio.get_running_loop().create_future()
        pending[counter] = future
        assert process.stdin is not None
        process.stdin.write((json.dumps({"id": counter, "method": method, "params": params}) + "\n").encode())
        await process.stdin.drain()
        response = await asyncio.wait_for(future, 90)
        if "error" in response:
            raise RuntimeError(response)
        return response["result"]

    def snapshot(label: str) -> list[int]:
        rows = []
        alive = []
        for line in pid_log.read_text().splitlines() if pid_log.exists() else []:
            pid, started = line.split()
            proc = Path("/proc") / pid
            row: dict[str, Any] = {"pid": int(pid), "wrapper_started_at": started, "alive": False}
            try:
                stat = (proc / "stat").read_text()
                # Zombies have exited but can remain visible until their parent reaps them.
                if stat.split(") ", 1)[1].split()[0] != "Z":
                    row.update(
                        stat=stat,
                        cmdline=(proc / "cmdline").read_text().replace("\x00", " "),
                        status=(proc / "status").read_text(),
                        smaps=(proc / "smaps_rollup").read_text(),
                        alive=True,
                    )
                    alive.append(int(pid))
            except (FileNotFoundError, ProcessLookupError):
                pass
            rows.append(row)
        record = {"label": label, "at": time.time(), "app_server_pid": process.pid, "servers": rows}
        with (output / "snapshots.jsonl").open("a") as out:
            out.write(json.dumps(record) + "\n")
        print(f"{mode}: {label}: live PIDs {alive}", flush=True)
        return alive

    async def unsubscribe(thread_id: str) -> None:
        await rpc("thread/unsubscribe", {"threadId": thread_id})
        for _ in range(100):
            if not snapshot("unload-wait"):
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("Owned server did not exit after thread unload")

    async def start() -> str:
        result = await rpc("thread/start", {"cwd": str(output), "ephemeral": True})
        return result["thread"]["id"]

    try:
        await rpc("initialize", {"clientInfo": {"name": "lazy-probe", "version": "1"}, "capabilities": {"experimentalApi": True}})
        process.stdin.write(b'{"method":"initialized"}\n')
        await process.stdin.drain()
        first = await start()
        await rpc("mcpServerStatus/list", {"threadId": first, "serverName": "okama", "detail": "toolsAndAuthOnly"})
        assert len(snapshot("cold-discovery")) == 1
        await unsubscribe(first)
        snapshot("cold-unloaded")
        second = await start()
        await asyncio.sleep(2)
        live = snapshot("warm-before-use")
        deferred = mode in {"lazy", "required-catalog"}
        assert len(live) == (0 if deferred else 1), (mode, live)
        # Also test shutting down a dormant runtime without launching its helper.
        if deferred:
            before = pid_log.read_text()
            await unsubscribe(second)
            assert pid_log.read_text() == before
            snapshot("dormant-unloaded")
            second = await start()
            await asyncio.sleep(2)
            assert not snapshot("warm-again-before-use")
        for number in (1, 2):
            started = time.monotonic()
            result = await rpc("mcpServer/tool/call", {"threadId": second, "server": "okama", "tool": "list_namespaces", "arguments": {}})
            elapsed = time.monotonic() - started
            (output / f"call-{number}.json").write_text(json.dumps({"elapsed_sec": elapsed, "response": result}))
            assert result.get("result", result).get("isError") is not True, result
            assert len(snapshot(f"call-{number}")) == 1
            print(f"{mode}: call {number}: {elapsed:.3f}s", flush=True)
        await asyncio.sleep(10)
        assert len(snapshot("subscribed-idle-10s")) == 1
        await unsubscribe(second)
        assert not snapshot("used-unloaded")
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 15)
        except TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await process.wait()
        await reader
        assert not snapshot("app-server-exit")
        events.close()
        stderr.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["lazy", "eager", "required", "required-catalog"])
    parser.add_argument("output", type=Path, help="New directory under the project's tmp/")
    args = parser.parse_args()
    destination = args.output.resolve()
    project_tmp = Path(__file__).resolve().parents[3] / "tmp"
    if not destination.is_relative_to(project_tmp):
        parser.error("Output must be under the project's tmp/")
    asyncio.run(probe(args.mode, destination))
