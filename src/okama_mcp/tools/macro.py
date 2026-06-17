"""Macroeconomic indicator tools: inflation and central-bank rates.

okama exposes inflation under the ``.INFL`` namespace (``USD.INFL``,
``EUR.INFL``, ``RUB.INFL`` ...) and central-bank rates under ``.RATE``
(``US.RATE``, ``ECB.RATE``, ``RUS.RATE``). To keep the LLM-facing API tidy
the tools accept either a bare currency / country code (``USD``, ``US``) or
the full symbol — we normalise.
"""

from __future__ import annotations

from typing import Any

import okama as ok
from fastmcp import FastMCP

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.serialization import dataframe_to_json, series_to_json, value_to_json


def _normalise_symbol(value: str, namespace: str) -> str:
    """Return ``value`` if it already carries a dotted namespace, else append one."""
    value = value.strip()
    if "." in value:
        return value.upper()
    return f"{value.upper()}.{namespace}"


def _metadata(obj: Any) -> dict[str, Any]:
    return {
        "symbol": getattr(obj, "symbol", None),
        "name": getattr(obj, "name", None),
        "country": getattr(obj, "country", None),
        "currency": getattr(obj, "currency", None),
        "type": getattr(obj, "type", None),
        "first_date": value_to_json(getattr(obj, "first_date", None)),
        "last_date": value_to_json(getattr(obj, "last_date", None)),
    }


# Curated central-bank key policy-rate aliases (friendly code -> real okama symbol).
# Values are verified to exist in the RATE namespace. Full symbols (with a dot)
# and underscored symbols (RUS_CBR, RUSFAR1M, ...) are passed through unchanged.
_RATE_ALIASES = {
    "US": "US_EFFR", "USA": "US_EFFR",
    "EU": "EU_MRO", "ECB": "EU_MRO",
    "RU": "RUS_CBR", "RUS": "RUS_CBR",
    "UK": "UK_BR", "GB": "UK_BR",
    "IL": "ISR_IR", "ISR": "ISR_IR",
    "CN": "CHN_LPR1", "CHN": "CHN_LPR1",
}


def _normalise_rate(value: str) -> str:
    """Map a friendly central-bank code to its key-rate symbol, else add ``.RATE``."""
    value = value.strip()
    if "." in value:
        return value.upper()
    key = value.upper()
    if key in _RATE_ALIASES:
        return f"{_RATE_ALIASES[key]}.RATE"
    return f"{key}.RATE"


def _normalise_indicator(value: str) -> str:
    """Resolve an indicator symbol; a bare country code defaults to CAPE10."""
    value = value.strip()
    if "." in value:
        return value.upper()
    if "_" in value:
        return f"{value.upper()}.RATIO"
    return f"{value.upper()}_CAPE10.RATIO"


_MACRO_NAMESPACES = ("INFL", "RATE", "RATIO")


def _resolve_plot_symbol(value: str) -> tuple[str, str]:
    """Resolve a macro symbol for plotting: (symbol, namespace_tag).

    A symbol with a namespace suffix routes by it; a bare code is treated as a
    CAPE10 country code (RATIO). Non-macro symbols raise OkamaMcpError.
    """
    value = value.strip()
    if "." in value:
        symbol = value.upper()
        namespace = symbol.rsplit(".", 1)[1]
        if namespace not in _MACRO_NAMESPACES:
            raise OkamaMcpError(
                f"{value!r} is not a macro symbol "
                "(expected an .INFL / .RATE / .RATIO suffix)"
            )
        return symbol, namespace
    return _normalise_indicator(value), "RATIO"


def _describe(obj: Any) -> dict[str, Any]:
    """Serialise a macro object's ``describe()`` table (small fixed-shape frame)."""
    return dataframe_to_json(obj.describe(), full=True)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@translates_okama_errors
def get_inflation(
    currency: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    include_cumulative: bool = False,
    include_rolling: bool = False,
    include_describe: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    """Return historical inflation for a currency.

    Parameters
    ----------
    currency : str, default 'USD'
        Either a bare currency code ('USD', 'EUR', 'RUB') or a full okama
        symbol ('USD.INFL').
    first_date, last_date : str, optional
        ISO 'YYYY-MM' bounds.
    include_cumulative : bool, default False
        Include the cumulative-inflation series. Omitted by default to keep
        responses compact — derivable from monthly series anyway.
    include_rolling : bool, default False
        Include the 12-month rolling inflation series.
    include_describe : bool, default False
        Include the describe() table (mean/median/max/min over YTD, 1/5/10y).
    full : bool, default False
        If True, return entire series. Otherwise long series are truncated.
    """
    symbol = _normalise_symbol(currency, "INFL")
    infl = ok.Inflation(symbol=symbol, first_date=first_date, last_date=last_date)

    out: dict[str, Any] = _metadata(infl)
    out["values_monthly"] = series_to_json(infl.values_monthly, full=full)
    out["annual_inflation"] = series_to_json(infl.annual_inflation_ts, full=True)
    out["purchasing_power_1000"] = value_to_json(getattr(infl, "purchasing_power_1000", None))
    if include_cumulative:
        out["cumulative_inflation"] = series_to_json(infl.cumulative_inflation, full=full)
    if include_rolling:
        out["rolling_inflation"] = series_to_json(infl.rolling_inflation, full=full)
    if include_describe:
        out["describe"] = _describe(infl)
    return out


@translates_okama_errors
def get_central_bank_rate(
    country: str = "US",
    first_date: str | None = None,
    last_date: str | None = None,
    frequency: str = "monthly",
    include_describe: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    """Return a historical central-bank / money-market rate.

    Parameters
    ----------
    country : str, default 'US'
        A friendly central-bank code mapped to its key policy rate
        ('US'->US_EFFR, 'EU'/'ECB'->EU_MRO, 'RUS'->RUS_CBR, 'UK'/'GB'->UK_BR,
        'ISR'->ISR_IR, 'CN'/'CHN'->CHN_LPR1), or a full okama symbol
        ('US_EFFR.RATE', 'RUONIA.RATE', 'RUSFAR1M.RATE'). Use
        search_assets(namespace='RATE') to discover all 41 rate symbols.
    first_date, last_date : str, optional
        ISO 'YYYY-MM' bounds.
    frequency : {'monthly', 'daily'}, default 'monthly'
        'daily' returns the daily rate series.
    include_describe : bool, default False
        Include the describe() table (mean/median/max/min over YTD, 1/5/10y).
    full : bool, default False
        If True, return the entire series. Otherwise long series are truncated.
    """
    if frequency not in ("monthly", "daily"):
        raise OkamaMcpError("frequency must be 'monthly' or 'daily'")
    symbol = _normalise_rate(country)
    rate = ok.Rate(symbol=symbol, first_date=first_date, last_date=last_date)

    out: dict[str, Any] = _metadata(rate)
    if frequency == "daily":
        out["values_daily"] = series_to_json(rate.values_daily, full=full)
    else:
        out["values_monthly"] = series_to_json(rate.values_monthly, full=full)
    if include_describe:
        out["describe"] = _describe(rate)
    return out


@translates_okama_errors
def get_indicator(
    symbol: str = "USA_CAPE10.RATIO",
    first_date: str | None = None,
    last_date: str | None = None,
    include_describe: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    """Return a macro indicator series (the RATIO namespace, e.g. CAPE10).

    Parameters
    ----------
    symbol : str, default 'USA_CAPE10.RATIO'
        A full okama symbol ('USA_CAPE10.RATIO'), an indicator code without the
        namespace ('USA_CAPE10' -> '...RATIO'), or a bare country code ('USA',
        'EUR') which defaults to that country's CAPE10. Use
        search_assets(namespace='RATIO') to list all available indicators.
    first_date, last_date : str, optional
        ISO 'YYYY-MM' bounds.
    include_describe : bool, default False
        Include the describe() table (mean/median/max/min over YTD, 1/5/10y).
    full : bool, default False
        If True, return the entire series. Otherwise long series are truncated.
    """
    resolved = _normalise_indicator(symbol)
    ind = ok.Indicator(symbol=resolved, first_date=first_date, last_date=last_date)

    out: dict[str, Any] = _metadata(ind)
    out["values_monthly"] = series_to_json(ind.values_monthly, full=full)
    if include_describe:
        out["describe"] = _describe(ind)
    return out


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register Phase 7 macro tools with the FastMCP server."""
    mcp.tool(get_inflation)
    mcp.tool(get_central_bank_rate)
    mcp.tool(get_indicator)
