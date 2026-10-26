"""Safe client-code tools; Planner exclusively owns database access."""
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from okama_mcp.schemas import ClientSafeChanges, ClientSafeResidency, get_planner_request_model
from okama_mcp.planner_localization import (
    Language, install_middleware, register_tool, presentation, present_client, present_residency,
)


def register(mcp: FastMCP, database: Path, language: Language = "en", *,
             allow_personal_data: bool = False) -> None:
    """Bind the privacy facade to an explicitly selected local database."""
    from okama_planner.ai import PlannerClientAccess

    service = PlannerClientAccess(database, allow_personal_data=allow_personal_data)
    install_middleware(mcp)

    def client_get(code: str, language: Language = "en") -> dict[str, Any]:
        """Read a client by code; personal fields require explicit local startup opt-in."""
        return present_client(service.client_get(code), language)

    def client_list(language: Language = "en") -> list[dict[str, Any]] | dict[str, Any]:
        """List clients; identity fields are pseudonymized unless local personal access is enabled."""
        records = service.client_list()
        if language == "en":
            return records
        return {"clients": records, "presentation": [presentation(record, language) for record in records]}

    def client_update(code: str, changes: ClientSafeChanges, language: Language = "en") -> dict[str, Any]:
        """Update client fields through Planner; local personal access is required."""
        payload = changes if isinstance(changes, dict) else changes.model_dump(exclude_unset=True)
        return present_client(service.client_update(code, payload), language)

    def client_set_tax_residency(code: str, residency: ClientSafeResidency,
                                 language: Language = "en") -> dict[str, Any]:
        """Record tax residence and an optional personal note through Planner."""
        return present_residency(service.client_set_tax_residency(code, residency.year, residency.country,
                                                                         getattr(residency, "note", None)), language)

    def client_get_tax_residency(code: str, year: int, language: Language = "en") -> dict[str, Any] | None:
        """Read an explicitly recorded year's country."""
        return present_residency(service.client_get_tax_residency(code, year), language)

    functions = [client_get, client_list, client_get_tax_residency]
    if allow_personal_data:
        from okama_planner.storage.validation import ResidencyDetails
        client_update.__annotations__["changes"] = dict[str, Any]
        client_set_tax_residency.__annotations__["residency"] = ResidencyDetails
        functions += [client_update, client_set_tax_residency]
    for function in functions:
        register_tool(mcp, function, function.__name__, language)
    _register_plan_tools(mcp, service, language, allow_personal_data)
    _register_personal_tools(mcp, service, language, allow_personal_data)


def _register_plan_tools(mcp: FastMCP, service: Any, language: Language, personal: bool) -> None:
    """Register versioned financial writes without direct database operations."""
    def client_save_plan(code: str, request: Any, language: Language = "en") -> dict[str, Any]:
        """Save a financial plan through Planner; return only its code and version."""
        return service.client_save_plan(code, request)

    client_save_plan.__annotations__["request"] = get_planner_request_model()

    def client_load_plan(code: str, version: int, language: Language = "en") -> dict[str, Any]:
        """Read a saved plan; labels are pseudonymized unless local personal access is enabled."""
        return service.client_load_plan(code, version)

    def client_list_plans(code: str, language: Language = "en") -> list[dict[str, Any]]:
        """List saved version identifiers without database contents."""
        return service.client_list_plans(code)

    def client_forecast(code: str, version: int, language: Language = "en") -> dict[str, Any]:
        """Calculate a saved version within Planner's privacy boundary."""
        return service.client_forecast(code, version)

    functions = [client_load_plan, client_list_plans, client_forecast]
    if personal:
        functions.append(client_save_plan)
    for function in functions:
        register_tool(mcp, function, function.__name__, language)


def _register_personal_tools(mcp: FastMCP, service: Any, language: Language, personal: bool) -> None:
    def client_meeting_list(code: str, language: Language = "en") -> list[dict[str, Any]]:
        """Read client meetings; free text is masked unless local personal access is enabled."""
        return service.meeting_list(code)

    register_tool(mcp, client_meeting_list, "client_meeting_list", language)
    if not personal:
        return

    def client_create(details: Any, language: Language = "en") -> dict[str, Any]:
        """Create a complete personal client record through Planner (local opt-in required)."""
        return service.client_create(details.model_dump(mode="json", exclude_unset=True))

    from okama_planner.storage.validation import ClientDetails
    client_create.__annotations__["details"] = ClientDetails

    def client_delete(code: str, language: Language = "en") -> dict[str, Any]:
        """Delete the selected client and all owned history through Planner."""
        return service.client_delete(code)

    def client_history(code: str, table: str, offset: int = 0, limit: int = 100,
                       language: Language = "en") -> dict[str, Any]:
        """Read a bounded page of the selected client's complete historical records through Planner."""
        return service.client_history(code, table, offset, limit)

    def client_meeting_save(code: str, meeting: dict[str, Any], meeting_id: int | None = None,
                            revision: str | None = None, language: Language = "en") -> dict[str, Any]:
        """Create or edit a personal meeting through Planner; editing requires its latest revision."""
        return service.meeting_save(code, meeting, meeting_id, revision)

    def client_meeting_delete(code: str, meeting_id: int, revision: str,
                              language: Language = "en") -> dict[str, Any]:
        """Delete a client-owned meeting through Planner, refusing stale revisions."""
        return service.meeting_delete(code, meeting_id, revision)

    for function in (client_create, client_delete, client_history, client_meeting_save, client_meeting_delete):
        register_tool(mcp, function, function.__name__, language)
