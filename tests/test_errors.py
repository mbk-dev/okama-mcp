"""Tests for okama_mcp.errors — translating okama exceptions into actionable MCP errors."""

from __future__ import annotations

import pytest

from okama_mcp.errors import OkamaMcpError, translate_exception


def test_symbol_not_found_message_suggests_search() -> None:
    exc = ValueError("symbol XXX.US is not in the list of assets")
    out = translate_exception(exc)
    assert isinstance(out, OkamaMcpError)
    assert "search_assets" in str(out).lower()


def test_weights_not_summing_to_one_is_rephrased() -> None:
    exc = ValueError("Sum of weights is not equal to 1: 0.97")
    out = translate_exception(exc)
    assert "weights" in str(out).lower()
    assert "1.0" in str(out)


def test_network_error_suggests_retry() -> None:
    exc = ConnectionError("Connection to api.okama.io reset")
    out = translate_exception(exc)
    assert "retry" in str(out).lower() or "network" in str(out).lower()


def test_generic_exception_is_wrapped() -> None:
    exc = RuntimeError("something went wrong")
    out = translate_exception(exc)
    assert isinstance(out, OkamaMcpError)
    assert "something went wrong" in str(out)


def test_okama_mcp_error_is_passed_through() -> None:
    """If we already have a domain error, don't re-wrap it."""
    original = OkamaMcpError("already nice")
    out = translate_exception(original)
    assert out is original


def test_exception_translator_decorator_translates_raises() -> None:
    from okama_mcp.errors import translates_okama_errors

    @translates_okama_errors
    def boom() -> None:
        raise ValueError("symbol ZZZ.US is not in the list of assets")

    with pytest.raises(OkamaMcpError) as ei:
        boom()
    assert "search_assets" in str(ei.value).lower()


def test_decorator_returns_value_on_success() -> None:
    from okama_mcp.errors import translates_okama_errors

    @translates_okama_errors
    def ok() -> int:
        return 42

    assert ok() == 42
