"""Verify the new MC-diagnostics and DCF tool modules are registered."""

from __future__ import annotations

import pytest


class TestNewToolsRegistered:
    @pytest.mark.asyncio
    async def test_new_tools_registered(self) -> None:
        from okama_mcp.server import mcp

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        expected = {
            "get_distribution_fit",
            "get_return_moments",
            "optimize_students_df",
            "get_cagr_distribution",
            "get_dcf_wealth_index",
            "get_dcf_cash_flow_ts",
            "get_dcf_wealth_with_assets",
            "get_survival_period",
            "get_initial_investment_values",
            "get_monte_carlo_cash_flow",
            "plot_qq",
            "plot_hist_fit",
        }
        missing = expected - names
        assert not missing, f"missing tools: {missing}"
        assert len(names) >= 45
