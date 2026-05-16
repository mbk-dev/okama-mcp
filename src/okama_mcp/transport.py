"""Command-line entry point for okama-mcp.

Usage:
    okama-mcp stdio
    okama-mcp http --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with `stdio` and `http` subcommands."""
    parser = argparse.ArgumentParser(
        prog="okama-mcp",
        description="MCP server exposing the okama investment toolkit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "stdio",
        help="Run the server over stdio (for Claude Desktop / Claude Code / Cursor)",
    )

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

    # Import lazily so that argument-only failures don't pull in okama/matplotlib.
    from okama_mcp.server import mcp

    if args.command == "stdio":
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
