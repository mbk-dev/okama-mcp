"""Client tools with a persistent access mode; Planner owns every database operation."""
from pathlib import Path
from typing import Any
from collections.abc import Callable

from fastmcp import FastMCP

from okama_mcp.client_data_access import ClientDataAccess, PersonalDataAccessRequired
from okama_mcp.schemas import (
    ClientDataMode, ClientPersonalChanges, ClientPersonalDetails, ClientPersonalResidency,
    get_planner_request_model,
)
from okama_mcp.planner_localization import (
    Language, install_middleware, register_tool, presentation, present_client, present_residency,
)


def register(mcp: FastMCP, database: Path, language: Language = "en", *,
             allow_personal_data: bool = False) -> None:
    """Bind Planner's access API to an explicitly selected local database."""
    from okama_planner.ai import PlannerClientAccess

    anonymous = PlannerClientAccess(database)
    personal = PlannerClientAccess(database, allow_personal_data=True)
    access = ClientDataAccess(database)
    _bootstrap_access(access, allow_personal_data)
    install_middleware(mcp)

    def service(write: bool = False) -> Any:
        enabled = access.get().mode == "personal_data"
        if write and not enabled:
            raise PersonalDataAccessRequired()
        return personal if enabled else anonymous

    def client_data_mode_get(language: Language = "en") -> dict[str, str]:
        """Read the saved client-data mode; a new database defaults to anonymous."""
        return access.get().model_dump()

    def client_data_mode_set(mode: ClientDataMode, language: Language = "en") -> dict[str, str]:
        """Save anonymous or personal_data mode for this database across MCP connections."""
        return access.set(mode).model_dump()

    for function in (client_data_mode_get, client_data_mode_set):
        register_tool(mcp, function, function.__name__, language)
    _register_client_tools(mcp, service, language)
    _register_plan_tools(mcp, service, language)
    _register_meeting_tools(mcp, service, language)


def _bootstrap_access(access: ClientDataAccess, allow_personal_data: bool) -> None:
    """Honor the legacy startup opt-in only before a persistent policy is recorded."""
    if type(allow_personal_data) is not bool:
        raise ValueError("Personal access requires an explicit boolean")
    if allow_personal_data and not access.path.exists():
        access.set("personal_data", only_if_absent=True)


def _register_client_tools(mcp: FastMCP, service: Callable[..., Any], language: Language) -> None:
    """Register client CRUD and residency tools behind the saved access policy."""
    def client_get(code: str, language: Language = "en") -> dict[str, Any]:
        """Read a client: pseudonyms in anonymous mode, full identity in personal_data mode."""
        return present_client(service().client_get(code), language)

    def client_list(language: Language = "en") -> list[dict[str, Any]] | dict[str, Any]:
        """List clients using the saved mode; anonymous mode returns pseudonyms."""
        records = service().client_list()
        if language == "en":
            return records
        return {"clients": records, "presentation": [presentation(record, language) for record in records]}

    def client_create(details: ClientPersonalDetails, language: Language = "en") -> dict[str, Any]:
        """Create a Planner client; requires the saved personal_data mode."""
        return present_client(service(write=True).client_create(details.model_dump(exclude_unset=True)), language)

    def client_update(code: str, changes: ClientPersonalChanges, language: Language = "en") -> dict[str, Any]:
        """Edit supplied client fields; requires personal_data mode. Omitted fields stay unchanged."""
        return present_client(service(write=True).client_update(code, changes.model_dump(exclude_unset=True)), language)

    def client_delete(code: str, language: Language = "en") -> dict[str, Any]:
        """Delete a client and all linked Planner records; requires personal_data mode."""
        return service(write=True).client_delete(code)

    def client_set_tax_residency(code: str, residency: ClientPersonalResidency,
                                 language: Language = "en") -> dict[str, Any]:
        """Save residence; omitted notes stay unchanged, null clears. Requires personal_data."""
        return present_residency(_save_residency(service(write=True), code, residency), language)

    def client_get_tax_residency(code: str, year: int, language: Language = "en") -> dict[str, Any] | None:
        """Read a year's residence; private notes are pseudonyms in anonymous mode."""
        return present_residency(service().client_get_tax_residency(code, year), language)

    for function in (client_get, client_list, client_create,
                     client_update, client_delete, client_set_tax_residency, client_get_tax_residency):
        register_tool(mcp, function, function.__name__, language)


def _save_residency(service: Any, code: str, residency: ClientPersonalResidency) -> dict[str, Any]:
    """Retain an existing private note when the caller only changes the country."""
    data = residency.model_dump()
    if "note" not in residency.model_fields_set:
        existing = service.client_get_tax_residency(code, residency.year)
        data["note"] = existing["note"] if existing else None
    return service.client_set_tax_residency(code, **data)


def _register_plan_tools(mcp: FastMCP, service: Callable[..., Any], language: Language) -> None:
    """Register versioned financial access through the same saved client-data policy."""
    def client_save_plan(code: str, request: Any, language: Language = "en") -> dict[str, Any]:
        """Save a financial plan through Planner; requires personal_data mode."""
        return service(write=True).client_save_plan(code, request)

    client_save_plan.__annotations__["request"] = get_planner_request_model()

    def client_load_plan(code: str, version: int, language: Language = "en") -> dict[str, Any]:
        """Read a saved plan; anonymous mode replaces identifying labels with pseudonyms."""
        return service().client_load_plan(code, version)

    def client_list_plans(code: str, language: Language = "en") -> list[dict[str, Any]]:
        """List saved version identifiers without client identities in either mode."""
        return service().client_list_plans(code)

    def client_forecast(code: str, version: int, language: Language = "en") -> dict[str, Any]:
        """Calculate a saved version; forecast output stays anonymous in both modes."""
        return service().client_forecast(code, version)

    for function in (client_save_plan, client_load_plan, client_list_plans, client_forecast):
        register_tool(mcp, function, function.__name__, language)


def _register_meeting_tools(mcp: FastMCP, service: Callable[..., Any], language: Language) -> None:
    """Preserve Planner meeting/history APIs under the same persistent access policy."""
    def client_meeting_list(code: str, language: Language = "en") -> list[dict[str, Any]]:
        """List meetings; anonymous mode masks private text."""
        return service().meeting_list(code)

    def client_history(code: str, table: str, offset: int = 0, limit: int = 100,
                       language: Language = "en") -> dict[str, Any]:
        """Read a bounded client history page; requires personal_data mode."""
        return service(write=True).client_history(code, table, offset, limit)

    def client_meeting_save(code: str, meeting: dict[str, Any], meeting_id: int | None = None,
                            revision: str | None = None, language: Language = "en") -> dict[str, Any]:
        """Create/edit a meeting in personal_data mode; edits require its latest revision."""
        return service(write=True).meeting_save(code, meeting, meeting_id, revision)

    def client_meeting_delete(code: str, meeting_id: int, revision: str,
                              language: Language = "en") -> dict[str, Any]:
        """Delete a meeting in personal_data mode; Planner rejects stale revisions."""
        return service(write=True).meeting_delete(code, meeting_id, revision)

    for function in (client_meeting_list, client_history, client_meeting_save, client_meeting_delete):
        register_tool(mcp, function, function.__name__, language)
