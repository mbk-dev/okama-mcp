"""Explicitly configured local Planner registry tools; never registered by register_all."""
from pathlib import Path
from typing import Any
from fastmcp import FastMCP

from okama_mcp.local_registry import create_client
from okama_mcp.schemas import get_client_models
from okama_mcp.planner_localization import Language, install_middleware, register_tool, presentation, present_client, present_residency


def register(mcp: FastMCP, database: Path, language: Language = "en") -> None:
    """Bind the selected existing database outside the MCP input contract."""
    install_middleware(mcp)
    from okama_planner.storage import PlannerStore
    details_model, residency_model = get_client_models()
    database = database.resolve(strict=True)
    with PlannerStore.open(database):
        pass

    def client_create(details: Any, request_id: str, allow_duplicate: bool = False, language: Language = "en") -> dict[str, Any]:
        """Create a local client. Reuse request_id on retries. Duplicates return candidates;
        allow_duplicate is only for an explicitly confirmed different namesake.
        """
        result = create_client(database, details.model_dump(mode="json"), request_id, allow_duplicate)
        if language != "en":
            records = [result["client"]] if "client" in result else result["candidates"]
            result["presentation"] = [presentation(record, language) for record in records]
        return result

    client_create.__annotations__["details"] = details_model
    register_tool(mcp, client_create, "client_create", language)

    def client_get(code: str, language: Language = "en") -> dict[str, Any]:
        """Read a complete local registry record by stable c-NNNN code."""
        with PlannerStore.open(database) as store:
            return present_client(store.get_client(code), language)

    def client_list(language: Language = "en") -> list[dict[str, Any]] | dict[str, Any]:
        """List local registry records, including possible duplicates before creation."""
        with PlannerStore.open(database) as store:
            records = store.list_clients()
            if language == "en":
                return records
            return {"clients": records, "presentation": [presentation(record, language) for record in records]}

    def client_update(code: str, changes: dict[str, Any], language: Language = "en") -> dict[str, Any]:
        """Patch a local record. Missing fields stay unchanged; null clears optional fields.
        Unknown/system fields fail. Planner validates the complete patched record.
        """
        with PlannerStore.open(database) as store:
            return present_client(store.update_client(code, changes), language)

    def client_set_tax_residency(code: str, residency: Any, language: Language = "en") -> dict[str, Any]:
        """Set or update one explicit year/country; this does not calculate jurisdictional taxes."""
        with PlannerStore.open(database) as store:
            record = store.set_tax_residency(code, **residency.model_dump())
            return present_residency(record, language)

    client_set_tax_residency.__annotations__["residency"] = residency_model
    register_tool(mcp, client_set_tax_residency, "client_set_tax_residency", language)

    def client_get_tax_residency(code: str, year: int, language: Language = "en") -> dict[str, Any] | None:
        """Read exactly this year's recorded residence; earlier years are never inherited."""
        with PlannerStore.open(database) as store:
            record = store.get_tax_residency(code, year)
            return present_residency(record, language)

    for function in (client_get, client_list, client_update, client_get_tax_residency):
        register_tool(mcp, function, function.__name__, language)
