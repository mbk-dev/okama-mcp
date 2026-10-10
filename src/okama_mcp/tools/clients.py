"""Safe client-code tools; Planner exclusively owns database access."""
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from okama_mcp.schemas import ClientSafeChanges, ClientSafeResidency, get_planner_request_model
from okama_mcp.planner_localization import (
    Language, install_middleware, register_tool, presentation, present_client, present_residency,
)


def register(mcp: FastMCP, database: Path, language: Language = "en") -> None:
    """Bind the privacy facade to an explicitly selected local database."""
    from okama_planner.ai import PlannerAI

    service = PlannerAI(database)
    install_middleware(mcp)

    def client_get(code: str, language: Language = "en") -> dict[str, Any]:
        """Read a pseudonymous client record by stable registry code."""
        return present_client(service.client_get(code), language)

    def client_list(language: Language = "en") -> list[dict[str, Any]] | dict[str, Any]:
        """List pseudonymous client records without names or contacts."""
        records = service.client_list()
        if language == "en":
            return records
        return {"clients": records, "presentation": [presentation(record, language) for record in records]}

    def client_update(code: str, changes: ClientSafeChanges, language: Language = "en") -> dict[str, Any]:
        """Update only sex, birth year or the investment declaration date."""
        return present_client(service.client_update(code, changes.model_dump(exclude_unset=True)), language)

    def client_set_tax_residency(code: str, residency: ClientSafeResidency,
                                 language: Language = "en") -> dict[str, Any]:
        """Record a year and country without personal notes."""
        return present_residency(service.client_set_tax_residency(code, residency.year, residency.country), language)

    def client_get_tax_residency(code: str, year: int, language: Language = "en") -> dict[str, Any] | None:
        """Read an explicitly recorded year's country."""
        return present_residency(service.client_get_tax_residency(code, year), language)

    for function in (client_get, client_list, client_update, client_set_tax_residency, client_get_tax_residency):
        register_tool(mcp, function, function.__name__, language)
    _register_plan_tools(mcp, service, language)


def _register_plan_tools(mcp: FastMCP, service: Any, language: Language) -> None:
    """Register versioned financial writes without direct database operations."""
    def client_save_plan(code: str, request: Any, language: Language = "en") -> dict[str, Any]:
        """Save a financial plan through Planner; return only its code and version."""
        return service.client_save_plan(code, request)

    client_save_plan.__annotations__["request"] = get_planner_request_model()

    def client_load_plan(code: str, version: int, language: Language = "en") -> dict[str, Any]:
        """Read a saved financial plan with pseudonymous labels."""
        return service.client_load_plan(code, version)

    def client_list_plans(code: str, language: Language = "en") -> list[dict[str, Any]]:
        """List saved version identifiers without database contents."""
        return service.client_list_plans(code)

    def client_forecast(code: str, version: int, language: Language = "en") -> dict[str, Any]:
        """Calculate a saved version within Planner's privacy boundary."""
        return service.client_forecast(code, version)

    for function in (client_save_plan, client_load_plan, client_list_plans, client_forecast):
        register_tool(mcp, function, function.__name__, language)
