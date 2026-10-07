"""Call the local stdio server twice with completely synthetic household plans."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main() -> None:
    source = Path(__file__).parent
    root = source.parents[1]
    output = root / "tmp" / "planner-mcp-demo"
    output.mkdir(parents=True, exist_ok=True)
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "okama_mcp.transport", "stdio"],
        cwd=str(root),
        env={"MPLBACKEND": "Agg"},
        keep_alive=False,
    )
    async with Client(transport) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert {"planner_forecast", "finplan_forecast", "finplan_backtest"} <= names
        schema = next(tool for tool in tools if tool.name == "planner_forecast")
        (output / "tool-schema.json").write_text(schema.model_dump_json(indent=2) + "\n")
        for name in ("baseline", "deferred"):
            request = json.loads((source / f"{name}-request.json").read_text())
            response = await client.call_tool_mcp("planner_forecast", {"request": request})
            result = json.loads(response.content[0].text)
            (output / f"{name}-result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
            print(f"{name}: {json.dumps(result['metrics'], sort_keys=True)}")
    print(f"Saved both MCP results to {output}")


if __name__ == "__main__":
    asyncio.run(main())
