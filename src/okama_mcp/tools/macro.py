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

from okama_mcp.errors import translates_okama_errors
from okama_mcp.serialization import series_to_json, value_to_json


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
    full: bool = False,
) -> dict[str, Any]:
    """Return historical central-bank rate.

    Parameters
    ----------
    country : str, default 'US'
        Either a bare country / central-bank code ('US', 'ECB', 'RUS') or a
        full okama symbol ('US.RATE').
    first_date, last_date : str, optional
        ISO 'YYYY-MM' bounds.
    full : bool, default False
        If True, return entire series. Otherwise long series are truncated.
    """
    symbol = _normalise_symbol(country, "RATE")
    rate = ok.Rate(symbol=symbol, first_date=first_date, last_date=last_date)

    out: dict[str, Any] = _metadata(rate)
    out["values_monthly"] = series_to_json(rate.values_monthly, full=full)
    return out


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register Phase 7 macro tools with the FastMCP server."""
    mcp.tool(get_inflation)
    mcp.tool(get_central_bank_rate)
