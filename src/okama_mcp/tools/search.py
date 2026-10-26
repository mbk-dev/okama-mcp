"""Search-and-metadata tools: ``search_assets``, ``list_namespaces``, ``get_asset_info``.

These are the first stop for any AI conversation about investments — the LLM
needs to translate a natural-language asset name ("gold ETF", "Apple stock")
into an okama ticker like ``GLD.US`` or ``AAPL.US`` before any other tool will
work. Namespace listing helps it understand what universes exist (US, MOEX,
INDX, INFL, ...).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import okama as ok
import pandas as pd
from fastmcp import FastMCP
from pydantic import Field

from okama_mcp.discovery import namespace_usage, reject_macro_symbols, symbol_namespace
from okama_mcp.errors import OkamaMcpError, PublicInputError, translates_okama_errors
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


def _search_columns(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Normalize nullable metadata for literal matching and deterministic ranking."""
    columns = {
        name: frame.get(name, pd.Series("", index=frame.index, dtype="string"))
        .astype("string").fillna("").str.casefold()
        for name in ("symbol", "ticker", "isin", "name", "local_name")
    }
    if "ticker" not in frame:
        columns["ticker"] = columns["symbol"].str.rsplit(".", n=1).str[0]
    return columns


def _search_candidates(query: str, namespace: str | None) -> pd.DataFrame:
    """Use okama's catalog for literal scoped searches, including full symbols."""
    if namespace is None and "." in query:
        suffix = query.rsplit(".", 1)[1].upper()
        if suffix in _get_namespaces():
            namespace = suffix
    if namespace is None:
        return ok.search(query, response_format="frame").copy()
    frame = ok.search("", namespace=namespace.upper(), response_format="frame").copy()
    if not query or frame.empty:
        return frame
    mask = pd.Series(False, index=frame.index)
    for values in _search_columns(frame).values():
        mask |= values.str.contains(query.casefold(), regex=False)
    return frame.loc[mask]


def _order_search(frame: pd.DataFrame, query: str, oldest_first: bool) -> pd.DataFrame:
    """Order the complete filtered set before any page is selected."""
    if frame.empty:
        return frame
    columns = _search_columns(frame)
    rank = pd.Series(3, index=frame.index)
    if query:
        value = query.casefold()
        for values in columns.values():
            rank.loc[values.str.startswith(value)] = 2
        for name in ("name", "local_name"):
            rank.loc[columns[name].eq(value)] = 1
        for name in ("symbol", "ticker", "isin"):
            rank.loc[columns[name].eq(value)] = 0
    ordering = pd.DataFrame({"symbol": columns["symbol"], "rank": rank}, index=frame.index)
    keys = ["rank", "symbol"] if query else ["symbol"]
    if oldest_first:
        if "first_date" not in frame:
            raise OkamaMcpError("okama search results do not include a first_date field")
        ordering["date"] = pd.to_datetime(frame["first_date"], errors="coerce")
        keys = ["date", "symbol"]
    order = ordering.sort_values(keys, kind="stable", na_position="last").index
    return frame.loc[order]


@translates_okama_errors
def search_assets(
    query: str = "",
    namespace: str | None = None,
    asset_type: str | None = None,
    oldest_first: bool = False,
    limit: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = MAX_RESULTS,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """Search for okama tickers by name, local name, ticker, or ISIN.

    Parameters
    ----------
    query : str
        Literal free-text query (case-insensitive). Exact identifiers and names
        rank before prefix/substring matches. Examples: 'gold', 'SPY', 'Apple',
        'Сбербанк', 'US78462F1030'. Leave empty only with ``namespace`` to
        browse that namespace.
    namespace : str, optional
        Restrict the search to one namespace (e.g. 'US', 'MOEX', 'XETR').
        Omit to search across all namespaces.
    asset_type : str, optional
        Restrict results to an exact okama ``type`` value, case-insensitively.
        For example, MOEX exchange-traded mutual funds (BPIFs) use ``'ETF'``.
    oldest_first : bool, default False
        Sort filtered results by ``first_date`` from oldest to newest. Missing
        dates are placed after dated records.
    limit : int, default 50
        Maximum number of rows to return (1 through 50).
    offset : int, default 0
        Number of filtered, ordered rows to skip. Follow ``next_offset`` for
        another page with the same query/filters. Pages use the current catalog;
        a catalog change between calls can change page boundaries.

    Returns
    -------
    dict with ``count``, ``truncated``, ``results``, ``offset``, ``limit``,
    ``has_more`` and ``next_offset`` (None on the final page). Each result row is a
    dict of asset metadata (symbol, name, local_name, country, currency, type,
    isin, first_date, namespace, supports_asset_returns, ...). ``count`` is the number after filtering and before
    applying pagination. ``truncated`` means this page is not the entire result
    set; use ``has_more`` to determine whether another page follows.
    """
    query = query.strip()
    namespace = namespace.strip().upper() if namespace is not None else None
    if not query and namespace is None:
        raise PublicInputError("query must be non-empty when namespace is omitted")
    if namespace == "":
        raise PublicInputError("namespace must be non-empty when provided")
    if not 1 <= limit <= MAX_RESULTS:
        raise PublicInputError(f"limit must be between 1 and {MAX_RESULTS}")
    if offset < 0:
        raise PublicInputError("offset must be non-negative")

    df = _search_candidates(query, namespace)
    if asset_type is not None:
        if "type" not in df.columns:
            raise OkamaMcpError("okama search results do not include a type field")
        types = df["type"].astype("string").str.casefold()
        df = df.loc[types == asset_type.casefold()]
    df = _order_search(df, query, oldest_first)

    total = int(len(df))
    rows = df.iloc[offset:offset + limit].to_dict(orient="records") if total else []
    has_more = offset + len(rows) < total
    assets, macro = _get_assets_namespaces(), _get_macro_namespaces()
    for row in rows:
        code = symbol_namespace(str(row.get("symbol", "")))
        row["namespace"] = code or None
        row["supports_asset_returns"] = namespace_usage(code, assets, macro)["supports_asset_returns"]
    return {
        "count": total,
        "truncated": len(rows) < total,
        "results": [{k: value_to_json(v) for k, v in row.items()} for row in rows],
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + len(rows) if has_more else None,
    }


@translates_okama_errors
def list_namespaces(kind: Literal["all", "assets", "macro"] = "all") -> dict[str, Any]:
    """List available okama namespaces.

    Parameters
    ----------
    kind : {'all', 'assets', 'macro'}, default 'all'
        - ``all`` — every namespace okama supports (assets + macro).
        - ``assets`` — only namespaces with price/return time series.
        - ``macro`` — only macroeconomic namespaces (INFL, RATE, ...).

    Returns
    -------
    dict with ``kind``, ``namespaces`` (mapping of code → description), and
    ``usage`` per namespace: ``kind`` (asset/macro/unknown),
    ``supports_asset_returns`` (true/false/null when unknown), and implemented
    ``tools``. RATE, INFL and RATIO are macro series, not portfolio assets.
    Browse symbols with search_assets(namespace=..., offset=...) and follow
    next_offset until has_more is false. Unknown routes have an empty tools list.
    """
    if kind == "all":
        ns = _get_namespaces()
    elif kind == "assets":
        ns = _get_assets_namespaces()
    elif kind == "macro":
        ns = _get_macro_namespaces()
    else:
        raise OkamaMcpError(f"kind must be one of {_VALID_KINDS}, got {kind!r}")
    descriptions = _as_code_to_description(ns)
    assets, macro = _get_assets_namespaces(), _get_macro_namespaces()
    return {"kind": kind, "namespaces": descriptions,
            "usage": {code: namespace_usage(code, assets, macro) for code in descriptions}}


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
        Asset ticker, e.g. 'GLD.US', 'AAPL.US', 'MCFTR.INDX'. For RATE,
        INFL and RATIO metadata use the macro tool advertised by list_namespaces.

    Returns
    -------
    dict with symbol, name, country, exchange, currency, type, isin,
    first_date, last_date, period_length_years, price (may be None for
    namespaces that don't support live prices).
    """
    reject_macro_symbols([symbol])
    asset = ok.Asset(symbol)
    return {
        "symbol": asset.symbol,
        "name": asset.name,
        "local_name": value_to_json(getattr(asset, "local_name", None)),
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
