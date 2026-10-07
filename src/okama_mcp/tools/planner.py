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
    Supports a single investment portfolio and separate goal portfolios with joint return
    history and explicit allocation. Use planner_compare_modes for a controlled mode comparison.
    Fixed-rate savings are separate from goal investment portfolios. Gamma, equivalent alpha,
    FX conversion and tax models are absent.
    """
    model = get_planner_request_model()
    if model is None:
        raise OkamaMcpError("To use planner_forecast, install the optional okama-planner companion package")
    from okama_planner import forecast

    validated = model.model_validate(request)
    return forecast(validated)


@translates_okama_errors
def planner_compare_modes(
    baseline: BaseModel | dict[str, Any], variant: BaseModel | dict[str, Any]
) -> dict[str, Any]:
    """Compare complete single/per_goal household forecast requests without session state.

    Keep family inputs, goals, joint history, seed and simulation count identical. Provide
    explicit allocation for goal portfolios. Returns both forecasts and their metrics, policy
    and risk differences. Fixed-rate savings are separate; Gamma, alpha and FX are unsupported.
    Requires a companion release exporting compare_portfolio_modes.
    """
    model = get_planner_request_model()
    if model is None:
        raise OkamaMcpError("To use planner_compare_modes, install the optional okama-planner companion package")
    validated_baseline = model.model_validate(baseline)
    validated_variant = model.model_validate(variant)
    import okama_planner

    compare = getattr(okama_planner, "compare_portfolio_modes", None)
    if compare is None:
        raise OkamaMcpError("To use planner_compare_modes, upgrade the okama-planner companion package")
    return compare(validated_baseline, validated_variant)


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

    import okama_planner

    if not callable(getattr(okama_planner, "compare_portfolio_modes", None)):
        return

    def compare(baseline: Any, variant: Any) -> dict[str, Any]:
        return planner_compare_modes(baseline, variant)

    compare.__annotations__["baseline"] = model
    compare.__annotations__["variant"] = model
    mcp.tool(compare, name="planner_compare_modes", description=planner_compare_modes.__doc__)
