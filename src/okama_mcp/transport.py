"""Command-line entry point for okama-mcp.

Usage:
    okama-mcp stdio
    okama-mcp http --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with `stdio` and `http` subcommands."""
    parser = argparse.ArgumentParser(
        prog="okama-mcp",
        description="MCP server exposing the okama investment toolkit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    stdio_parser = subparsers.add_parser(
        "stdio",
        help="Run the server over stdio (for Claude Desktop / Claude Code / Cursor)",
    )

    stdio_parser.add_argument("--client-db", type=Path, help="Explicit existing local Planner database (POSIX)")
    stdio_parser.add_argument("--reports-dir", type=Path, help="Existing local report output directory")
    stdio_parser.add_argument("--report-brand", type=Path, help="Local Planner ReportBrand JSON file")
    initialize = subparsers.add_parser("init-client-db", help="Create a new empty Planner database")
    initialize.add_argument("--path", type=Path, required=True)

    skill = subparsers.add_parser("install-skill", help="Install the packaged create-client skill")
    skill.add_argument("--destination", type=Path, required=True, help="Project .agents/skills directory")

    http_parser = subparsers.add_parser(
        "http",
        help="Run the server over streamable HTTP (for remote clients)",
    )
    http_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1)",
    )
    http_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind (default: 8765)",
    )
    http_parser.add_argument(
        "--path",
        default="/mcp",
        help="HTTP path for the MCP endpoint (default: /mcp)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a POSIX exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "install-skill":
        from okama_mcp.skills import install_skill
        print(f"Installed {install_skill(args.destination)}")
        return 0

    if args.command == "init-client-db":
        from okama_planner.storage import PlannerStore
        if not args.path.is_absolute():
            parser.error("--path must be absolute")
        with PlannerStore.initialize(args.path):
            pass
        return 0

    # Import lazily so that argument-only failures don't pull in okama/matplotlib.
    from okama_mcp.server import create_server

    mcp = create_server()

    if args.command == "stdio":
        if args.client_db:
            if not args.client_db.is_absolute():
                parser.error("--client-db must be absolute")
            from okama_mcp.tools import clients
            clients.register(mcp, args.client_db)
        if args.report_brand and not args.reports_dir:
            parser.error("--report-brand requires --reports-dir")
        if args.reports_dir:
            from okama_mcp.tools import planner_reports
            planner_reports.register(mcp, args.reports_dir, args.report_brand)
        mcp.run()
        return 0

    if args.command == "http":
        mcp.run(
            transport="http",
            host=args.host,
            port=args.port,
            path=args.path,
        )
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2  # unreachable; parser.error raises SystemExit


if __name__ == "__main__":
    sys.exit(main())
