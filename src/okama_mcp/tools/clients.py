"""Explicitly configured local Planner registry tools; never registered by register_all."""
from pathlib import Path
from typing import Any
from fastmcp import FastMCP

from okama_mcp.local_registry import create_client
from okama_mcp.schemas import get_client_models


def register(mcp: FastMCP, database: Path) -> None:
    """Bind the selected existing database outside the MCP input contract."""
    from okama_planner.storage import PlannerStore
    details_model, residency_model = get_client_models()
    database = database.resolve(strict=True)
    with PlannerStore.open(database):
        pass

    def client_create(details: Any, request_id: str, allow_duplicate: bool = False) -> dict[str, Any]:
        """Create a local client. Reuse request_id on retries. Duplicates return candidates;
        allow_duplicate is only for an explicitly confirmed different namesake.
        """
        return create_client(database, details.model_dump(mode="json"), request_id, allow_duplicate)

    client_create.__annotations__["details"] = details_model
    mcp.tool(client_create)

    @mcp.tool
    def client_get(code: str) -> dict[str, Any]:
        """Read a complete local registry record by stable c-NNNN code."""
        with PlannerStore.open(database) as store:
            return store.get_client(code)

    @mcp.tool
    def client_list() -> list[dict[str, Any]]:
        """List local registry records, including possible duplicates before creation."""
        with PlannerStore.open(database) as store:
            return store.list_clients()

    @mcp.tool
    def client_update(code: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Patch a local record. Missing fields stay unchanged; null clears optional fields.
        Unknown/system fields fail. Planner validates the complete patched record.
        """
        with PlannerStore.open(database) as store:
            return store.update_client(code, changes)

    def client_set_tax_residency(code: str, residency: Any) -> dict[str, Any]:
        """Set or update one explicit year/country; this does not calculate jurisdictional taxes."""
        with PlannerStore.open(database) as store:
            return store.set_tax_residency(code, **residency.model_dump())

    client_set_tax_residency.__annotations__["residency"] = residency_model
    mcp.tool(client_set_tax_residency)

    @mcp.tool
    def client_get_tax_residency(code: str, year: int) -> dict[str, Any] | None:
        """Read exactly this year's recorded residence; earlier years are never inherited."""
        with PlannerStore.open(database) as store:
            return store.get_tax_residency(code, year)
