"""Compare synthetic portfolio modes through the complete local stdio MCP server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    fixtures = root / "examples" / "planner"
    output = root / "tmp" / "planner-modes-mcp"
    output.mkdir(parents=True, exist_ok=True)
    # Use this checkout even when an editable-install .pth points at another worktree.
    pythonpath = os.pathsep.join(filter(None, [str(root / "src"), os.environ.get("PYTHONPATH", "")]))
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "okama_mcp.transport", "stdio"],
        cwd=str(root),
        env={"MPLBACKEND": "Agg", "PYTHONPATH": pythonpath},
        keep_alive=False,
    )
    async with Client(transport) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        required = {"planner_forecast", "planner_compare_modes", "finplan_forecast", "finplan_backtest"}
        missing = required - tools.keys()
        if missing:
            raise RuntimeError(f"Missing tools {sorted(missing)}; reinstall MCP 2.0.0 with okama Planner >=0.4.0")
        for name in ("planner_forecast", "planner_compare_modes"):
            (output / f"{name}-schema.json").write_text(tools[name].model_dump_json(indent=2) + "\n")
        requests = {
            mode: json.loads((fixtures / f"modes-{mode}-request.json").read_text())
            for mode in ("single", "per_goal")
        }
        response = await client.call_tool_mcp(
            "planner_compare_modes", {"baseline": requests["single"], "variant": requests["per_goal"]}
        )
        if response.model_dump(by_alias=True)["isError"]:
            raise RuntimeError(response.content[0].text)
        result = json.loads(response.content[0].text)
        (output / "comparison-result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        for side in ("baseline", "variant"):
            forecast = result[side]
            funded = {str(goal["goal_id"]): goal["p_funded"] for goal in forecast["goals"]}
            success = forecast["metrics"]["probability_of_success"]
            print(f"{forecast['portfolio_mode']}: full-plan success={success}; goal funding={json.dumps(funded)}")
    print("The separate mode retains more capital because its purchase is unfunded.")
    print(f"Saved comparison and complete MCP schemas to {output}")


if __name__ == "__main__":
    asyncio.run(main())
