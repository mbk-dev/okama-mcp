"""Search-and-metadata tools: ``search_assets``, ``list_namespaces``, ``get_asset_info``.

These are the first stop for any AI conversation about investments — the LLM
needs to translate a natural-language asset name ("gold ETF", "Apple stock")
into an okama ticker like ``GLD.US`` or ``AAPL.US`` before any other tool will
work. Namespace listing helps it understand what universes exist (US, MOEX,
INDX, INFL, ...).
"""

from __future__ import annotations

from typing import Any

import okama as ok
from fastmcp import FastMCP

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.serialization import value_to_json

MAX_RESULTS = 50
_VALID_KINDS = ("all", "assets", "macro")


# ---------------------------------------------------------------------------
# Indirection so tests can stub the namespace getters without touching okama
# globals (which are read-only properties on the package).
# ---------------------------------------------------------------------------


def _get_namespaces() -> dict[str, str]:
    return ok.namespaces


def _get_assets_namespaces() -> dict[str, str]:
    return ok.assets_namespaces


def _get_macro_namespaces() -> dict[str, str]:
    return ok.macro_namespaces


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@translates_okama_errors
def search_assets(query: str, namespace: str | None = None) -> dict[str, Any]:
    """Search for okama tickers by name, ticker, or ISIN.

    Parameters
    ----------
    query : str
        Free-text query (case-insensitive). Examples: 'gold', 'SPY', 'Apple',
        'US78462F1030'.
    namespace : str, optional
        Restrict the search to one namespace (e.g. 'US', 'MOEX', 'XETR').
        Omit to search across all namespaces.

    Returns
    -------
    dict with keys ``count``, ``truncated``, ``results``. Each result row is a
    dict of asset metadata (symbol, name, country, currency, type, isin, ...).
    """
    df = ok.search(query, namespace=namespace, response_format="frame")
    total = int(len(df))
    truncated = total > MAX_RESULTS
    rows = df.head(MAX_RESULTS).to_dict(orient="records") if total else []
    return {
        "count": total,
        "truncated": truncated,
        "results": [{k: value_to_json(v) for k, v in row.items()} for row in rows],
    }


@translates_okama_errors
def list_namespaces(kind: str = "all") -> dict[str, Any]:
    """List available okama namespaces.

    Parameters
    ----------
    kind : {'all', 'assets', 'macro'}, default 'all'
        - ``all`` — every namespace okama supports (assets + macro).
        - ``assets`` — only namespaces with price/return time series.
        - ``macro`` — only macroeconomic namespaces (INFL, RATE, ...).

    Returns
    -------
    dict with ``kind`` and ``namespaces`` (mapping of code → description).
    """
    if kind == "all":
        ns = _get_namespaces()
    elif kind == "assets":
        ns = _get_assets_namespaces()
    elif kind == "macro":
        ns = _get_macro_namespaces()
    else:
        raise OkamaMcpError(f"kind must be one of {_VALID_KINDS}, got {kind!r}")
    return {"kind": kind, "namespaces": _as_code_to_description(ns)}


def _as_code_to_description(ns: dict[str, str] | list[str]) -> dict[str, str]:
    """Normalise okama's namespace getters to a ``{code: description}`` mapping.

    okama 2.2 is inconsistent: ``ok.namespaces`` is a ``{code: description}``
    dict, but ``ok.assets_namespaces`` / ``ok.macro_namespaces`` return a bare
    ``list`` of codes. Calling ``dict()`` on the list shape raises
    ``ValueError: dictionary update sequence element ... has length N``. For the
    list shape we look each code's description up in the full namespace mapping
    (which covers every code), falling back to an empty string.
    """
    if isinstance(ns, dict):
        return dict(ns)
    full = _get_namespaces()
    descriptions = full if isinstance(full, dict) else {}
    return {code: descriptions.get(code, "") for code in ns}


def _safe_price(asset: Any) -> float | None:
    try:
        price = asset.price
    except AttributeError:
        return None
    except Exception:  # noqa: BLE001 — okama can raise various network/HTTP errors here
        return None
    return value_to_json(price)


@translates_okama_errors
def get_asset_info(symbol: str) -> dict[str, Any]:
    """Get metadata for a single asset by symbol.

    Parameters
    ----------
    symbol : str
        okama ticker, e.g. 'GLD.US', 'AAPL.US', 'MCFTR.INDX'.

    Returns
    -------
    dict with symbol, name, country, exchange, currency, type, isin,
    first_date, last_date, period_length_years, price (may be None for
    namespaces that don't support live prices).
    """
    asset = ok.Asset(symbol)
    return {
        "symbol": asset.symbol,
        "name": asset.name,
        "country": asset.country,
        "exchange": asset.exchange,
        "currency": asset.currency,
        "type": asset.type,
        "isin": asset.isin,
        "first_date": value_to_json(asset.first_date),
        "last_date": value_to_json(asset.last_date),
        "period_length_years": value_to_json(asset.period_length),
        "price": _safe_price(asset),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register Phase 2 tools with the given FastMCP server."""
    mcp.tool(search_assets)
    mcp.tool(list_namespaces)
    mcp.tool(get_asset_info)
