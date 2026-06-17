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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register Phase 7 macro tools with the FastMCP server."""
    mcp.tool(get_inflation)
    mcp.tool(get_central_bank_rate)
