"""Shared namespace routes for discovery and asset-input corrections."""

from collections.abc import Iterable
from typing import Any

from okama_mcp.errors import PublicInputError

MACRO_ROUTES = {
    "INFL": ("get_inflation", "currency"),
    "RATE": ("get_central_bank_rate", "country"),
    "RATIO": ("get_indicator", "symbol"),
}


def symbol_namespace(symbol: str) -> str:
    """Extract an explicit namespace without guessing a default market."""
    return symbol.strip().rpartition(".")[2].upper() if "." in symbol else ""


def namespace_usage(code: str, assets: Iterable[str], macro: Iterable[str]) -> dict[str, Any]:
    """Describe upstream membership separately from implemented MCP routes."""
    if code in MACRO_ROUTES or code in macro:
        route = MACRO_ROUTES.get(code)
        return {"kind": "macro", "supports_asset_returns": False,
                "tools": [route[0], "plot_macro"] if route else []}
    if code in assets:
        return {"kind": "asset", "supports_asset_returns": True,
                "tools": ["get_asset_info", "get_asset_returns", "analyze_portfolio"]}
    return {"kind": "unknown", "supports_asset_returns": None, "tools": []}


def reject_macro_symbols(symbols: Iterable[str]) -> None:
    """Reject known macro series before passing asset inputs to okama.

    Messages use only fixed route names; never disclose arbitrary inputs or
    backend exception text through the server's error-masking boundary.
    """
    for symbol in symbols:
        namespace = symbol_namespace(symbol)
        if namespace in MACRO_ROUTES:
            tool, parameter = MACRO_ROUTES[namespace]
            raise PublicInputError(
                f"{namespace} contains macroeconomic series and cannot be used as asset returns. "
                f"Use search_assets(namespace='{namespace}') to discover symbols, then "
                f"{tool}({parameter}=<full symbol>) for values and metadata. "
                "For an investable index, discover its symbol separately with search_assets(namespace='INDX'); "
                "a macro series is not automatically replaced by an investment return series."
            )
