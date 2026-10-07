"""Optional household-planning adapter; all financial calculations belong to okama Planner."""

from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.schemas import get_planner_request_model


@translates_okama_errors
def planner_forecast(request: BaseModel | dict[str, Any]) -> dict[str, Any]:
    """Calculate a complete household plan: budget, loans, assets, goals and retirement spending.

    Pass the full request on every call. Frozen stage return samples allow offline forecasts;
    holdings require market-data access. Returns the versioned ledger, portfolio flows, goal
    affordability/survival, full-plan success, portfolio/net-capital chart series and provenance.
    For comparisons, make separate calls with copied requests and an altered goal date. Only
    the single investment-portfolio mode is supported; fixed-rate savings are not goal-specific
    investment portfolios. Gamma, equivalent alpha, FX conversion and tax models are absent.
    """
    model = get_planner_request_model()
    if model is None:
        raise OkamaMcpError("To use planner_forecast, install the optional okama-planner companion package")
    from okama_planner import forecast

    validated = model.model_validate(request)
    return forecast(validated)


def register(mcp: FastMCP) -> None:
    """Expose the actual companion schema without copying it or requiring it for other tools."""
    model = get_planner_request_model()
    if model is None:
        return

    def call(request: Any) -> dict[str, Any]:
        return planner_forecast(request)

    # FastMCP derives the complete nested input contract from this runtime Pydantic model.
    call.__annotations__["request"] = model
    mcp.tool(call, name="planner_forecast", description=planner_forecast.__doc__)
