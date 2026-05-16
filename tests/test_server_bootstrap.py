"""Phase 0 smoke tests: the FastMCP server can be constructed and the CLI is wired up."""

from __future__ import annotations

from fastmcp import FastMCP


def test_mcp_instance_is_a_fastmcp_server() -> None:
    """The package exposes a `mcp` attribute that is a configured FastMCP instance."""
    from okama_mcp.server import mcp

    assert isinstance(mcp, FastMCP)


def test_mcp_server_has_expected_name() -> None:
    """The server identifies itself as `okama-mcp` so MCP clients can recognise it."""
    from okama_mcp.server import mcp

    assert mcp.name == "okama-mcp"


def test_transport_cli_exposes_stdio_and_http_subcommands() -> None:
    """The CLI parser must accept both `stdio` and `http` subcommands."""
    from okama_mcp.transport import build_parser

    parser = build_parser()

    stdio_ns = parser.parse_args(["stdio"])
    assert stdio_ns.command == "stdio"

    http_ns = parser.parse_args(["http", "--host", "0.0.0.0", "--port", "9000"])
    assert http_ns.command == "http"
    assert http_ns.host == "0.0.0.0"
    assert http_ns.port == 9000
