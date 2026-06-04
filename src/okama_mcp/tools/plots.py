"""Chart tools: render okama data as PNG images (MCP image content).

Each tool reuses the cached object builders of its data-returning sibling
(`portfolio._get_portfolio`, `frontier._get_frontier`, ...) and draws with
the thread-safe OO matplotlib helpers from `okama_mcp.rendering`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from okama_mcp.errors import translates_okama_errors
from okama_mcp.rendering import fig_to_png, make_figure
from okama_mcp.tools.asset_list import _build_asset_list
from okama_mcp.tools.frontier import _get_frontier
from okama_mcp.tools.monte_carlo import _prepare_dcf
from okama_mcp.tools.portfolio import _get_portfolio


def _png(fig: Any) -> Image:
    return Image(data=fig_to_png(fig), format="png")


def _plot_index_values(index: pd.Index) -> pd.Index:
    """PeriodIndex can't be plotted directly — convert to timestamps."""
    return index.to_timestamp() if isinstance(index, pd.PeriodIndex) else index


@translates_okama_errors
def plot_wealth_index(
    portfolio: dict[str, Any], width: int = 1500, height: int = 900
) -> Image:
    """Line chart of the portfolio wealth index (growth of 1000 units).

    Includes the accumulated-inflation line when the spec has ``inflation: true``.
    ``width``/``height`` set the PNG size in pixels (300-4000) — use them when the
    user asks for a specific size or aspect ratio.
    """
    spec, pf = _get_portfolio(portfolio)
    wi = pf.wealth_index
    fig, ax = make_figure(width, height)
    x = _plot_index_values(wi.index)
    for col in wi.columns:
        ax.plot(x, wi[col].astype(float).values, label=str(col))
    ax.set_title(f"Wealth index — {', '.join(spec.assets)} ({spec.ccy})")
    ax.set_ylabel(f"Wealth ({spec.ccy})")
    ax.legend()
    return _png(fig)


@translates_okama_errors
def plot_drawdowns(
    portfolio: dict[str, Any], width: int = 1500, height: int = 900
) -> Image:
    """Drawdown chart for the portfolio (percentage decline from previous peak).

    ``width``/``height``: PNG size in pixels (300-4000) for custom sizes/aspect ratios.
    """
    spec, pf = _get_portfolio(portfolio)
    dd = pf.drawdowns.astype(float)
    fig, ax = make_figure(width, height)
    x = _plot_index_values(dd.index)
    ax.plot(x, dd.values, color="tab:red")
    ax.fill_between(x, dd.values, 0.0, color="tab:red", alpha=0.25)
    ax.set_title(f"Drawdowns — {', '.join(spec.assets)} ({spec.ccy})")
    ax.set_ylabel("Drawdown")
    return _png(fig)


@translates_okama_errors
def plot_efficient_frontier(
    frontier: dict[str, Any], width: int = 1500, height: int = 900
) -> Image:
    """Efficient-frontier curve (Risk vs Mean return) with individual asset points.

    ``width``/``height``: PNG size in pixels (300-4000) for custom sizes/aspect ratios.
    """
    spec, ef = _get_frontier(frontier)
    points = ef.ef_points
    fig, ax = make_figure(width, height)
    ax.plot(
        points["Risk"].astype(float).values,
        points["Mean return"].astype(float).values,
        marker="o", markersize=3, label="Efficient frontier",
    )
    # Individual assets: risk/return Series may include inflation — keep symbols only.
    risks = ef.risk_annual
    returns = ef.mean_return
    for symbol in ef.symbols:
        if symbol in risks.index and symbol in returns.index:
            ax.scatter(float(risks[symbol]), float(returns[symbol]), zorder=3)
            ax.annotate(symbol, (float(risks[symbol]), float(returns[symbol])),
                        textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax.set_title(f"Efficient frontier — {', '.join(spec.assets)} ({spec.ccy})")
    ax.set_xlabel("Risk (annualized std)")
    ax.set_ylabel("Mean return (annualized)")
    ax.legend()
    return _png(fig)


@translates_okama_errors
def plot_monte_carlo(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    cashflow: dict[str, Any],
    width: int = 1500,
    height: int = 900,
) -> Image:
    """Monte Carlo forecast fan: percentile bands of future wealth over time.

    ``width``/``height``: PNG size in pixels (300-4000) for custom sizes/aspect ratios.
    """
    pf, mc_spec = _prepare_dcf(portfolio, mc, cashflow)
    mc_wealth = pf.dcf.monte_carlo_wealth(discounting="fv", include_negative_values=True)

    fig, ax = make_figure(width, height)
    x = _plot_index_values(mc_wealth.index)
    percentiles = sorted(mc_spec.percentiles)
    bands = {p: mc_wealth.quantile(p / 100.0, axis=1) for p in percentiles}
    for p, series in bands.items():
        ax.plot(x, series.values, label=f"p{p}")
    if len(percentiles) >= 2:
        ax.fill_between(x, bands[percentiles[0]].values, bands[percentiles[-1]].values,
                        alpha=0.15)
    ax.set_title(
        f"Monte Carlo forecast — {mc_spec.scenarios} scenarios, "
        f"{mc_spec.period_years}y ({mc_spec.distribution})"
    )
    ax.set_ylabel(f"Wealth ({getattr(pf, 'currency', '')})")
    ax.legend()
    return _png(fig)


@translates_okama_errors
def plot_assets(
    symbols: list[str],
    ccy: str,
    first_date: str | None = None,
    last_date: str | None = None,
    inflation: bool = False,
    width: int = 1500,
    height: int = 900,
) -> Image:
    """Wealth-index comparison chart for individual assets (growth of 1000 each).

    ``width``/``height``: PNG size in pixels (300-4000) for custom sizes/aspect ratios.
    """
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation)
    wi = al.wealth_indexes
    fig, ax = make_figure(width, height)
    x = _plot_index_values(wi.index)
    for col in wi.columns:
        ax.plot(x, wi[col].astype(float).values, label=str(col))
    ax.set_title(f"Wealth indexes — {', '.join(symbols)} ({ccy})")
    ax.set_ylabel(f"Wealth ({ccy})")
    ax.legend()
    return _png(fig)


def register(mcp: FastMCP) -> None:
    """Register chart tools with the FastMCP server."""
    mcp.tool(plot_wealth_index)
    mcp.tool(plot_drawdowns)
    mcp.tool(plot_efficient_frontier)
    mcp.tool(plot_monte_carlo)
    mcp.tool(plot_assets)
