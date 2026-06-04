"""Translate okama exceptions into actionable MCP-tool errors.

okama raises plain ``ValueError`` / ``TypeError`` with messages aimed at Python
developers ("symbol XXX.US is not in the list of assets", "Sum of weights is not
equal to 1"). When the caller is an LLM driving the tool, we want errors that
*tell it what to do next* — e.g. "use search_assets to find the right ticker".

The translator inspects the exception message with cheap substring matching. We
deliberately keep the rule set small and only handle high-traffic cases; anything
else passes through with its original message preserved.
"""

from __future__ import annotations

import functools
from typing import Any, TypeVar
from collections.abc import Callable


class OkamaMcpError(RuntimeError):
    """Domain error surfaced by okama-mcp tools.

    FastMCP will render this as a tool error to the LLM with the message intact.
    """


def _suggest_for_symbol_not_found(message: str) -> str:
    return (
        f"{message}. "
        "Use search_assets(query, namespace?) to find the correct ticker — "
        "okama tickers look like 'SPY.US', 'GLD.US', 'VNQ.US', 'MCFTR.INDX', 'USD.INFL'."
    )


def _suggest_for_weights(message: str) -> str:
    return (
        f"{message}. "
        "Portfolio weights must sum to exactly 1.0 (each in the 0..1 range) and "
        "have the same length as the assets list."
    )


def _suggest_for_network(message: str) -> str:
    return (
        f"Network error talking to api.okama.io: {message}. "
        "This is usually transient — retry the tool call; if it persists, the "
        "data API may be down."
    )


def _classify(exc: Exception) -> str:
    msg = str(exc).lower()
    if "is not in the list" in msg or "symbol" in msg and "not" in msg and "found" in msg:
        return "symbol_not_found"
    if "weights" in msg and ("sum" in msg or "equal to 1" in msg):
        return "weights"
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "network"
    if "connection" in msg or "timeout" in msg or "api.okama.io" in msg:
        return "network"
    return "generic"


def translate_exception(exc: Exception) -> OkamaMcpError:
    """Wrap an okama exception in an :class:`OkamaMcpError` with a helpful message.

    Already-typed :class:`OkamaMcpError` instances pass through unchanged.
    """
    if isinstance(exc, OkamaMcpError):
        return exc

    category = _classify(exc)
    original = str(exc)
    if category == "symbol_not_found":
        return OkamaMcpError(_suggest_for_symbol_not_found(original))
    if category == "weights":
        return OkamaMcpError(_suggest_for_weights(original))
    if category == "network":
        return OkamaMcpError(_suggest_for_network(original))
    return OkamaMcpError(original)


T = TypeVar("T")


def translates_okama_errors(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator that catches exceptions inside a tool and re-raises as :class:`OkamaMcpError`."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return func(*args, **kwargs)
        except OkamaMcpError:
            raise
        except Exception as exc:  # noqa: BLE001 — intentional broad catch at tool boundary
            raise translate_exception(exc) from exc

    return wrapper
