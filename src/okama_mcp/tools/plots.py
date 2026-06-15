"""Chart tools: render okama data as PNG images (MCP image content).

Each tool reuses the cached object builders of its data-returning sibling
(`portfolio._get_portfolio`, `frontier._get_frontier`, ...) and draws with
the thread-safe OO matplotlib helpers from `okama_mcp.rendering`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy.stats
from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.rendering import fig_to_png, make_figure
from okama_mcp.tools.asset_list import _build_asset_list
from okama_mcp.tools.frontier import _get_frontier
from okama_mcp.tools.monte_carlo import _prepare_dcf, _prepare_mc
from okama_mcp.tools.portfolio import _get_portfolio

_TM_NON_WEIGHT_COLS = {"Risk", "Mean return", "CAGR", "Weights", "iterations", "init_guess"}


def _render(fig: Any, save_path: str | None) -> Image | list[Image | str]:
    """Return the chart as MCP image content; optionally also write it to disk.

    ``save_path`` exists for clients that don't render MCP images in their UI
    (e.g. terminal clients like Claude Code): the tool writes the PNG to the
    given path and reports it, so the user gets an openable file reference.
    """
    png = fig_to_png(fig)
    image = Image(data=png, format="png")
    if save_path is None:
        return image
    path = Path(save_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return [image, f"Chart saved to {path}"]


def _plot_index_values(index: pd.Index) -> pd.Index:
    """PeriodIndex can't be plotted directly — convert to timestamps."""
    return index.to_timestamp() if isinstance(index, pd.PeriodIndex) else index


def _join_symbols(obj: Any, spec: Any) -> str:
    """Comma-joined resolved symbols for chart titles (nesting-safe).

    Prefer the built object's ``.symbols`` (resolved, incl. nested-portfolio
    ``.PF`` labels); fall back to the spec's string tickers only.
    """
    syms = getattr(obj, "symbols", None)
    items = list(syms) if syms is not None else [a for a in spec.assets if isinstance(a, str)]
    return ", ".join(str(s) for s in items)


@translates_okama_errors
def plot_wealth_index(
    portfolio: dict[str, Any], width: int = 1500, height: int = 900, save_path: str | None = None
) -> Image | list[Image | str]:
    """Line chart of the portfolio wealth index (growth of 1000 units).

    Includes the accumulated-inflation line when the spec has ``inflation: true``.
    ``width``/``height`` set the PNG size in pixels (300-4000) — use them when the
    user asks for a specific size or aspect ratio.
    ``save_path``: optional file path — also write the PNG there and report it
    (for clients that don't render MCP images inline, e.g. terminal clients).
    """
    spec, pf = _get_portfolio(portfolio)
    wi = pf.wealth_index
    fig, ax = make_figure(width, height)
    x = _plot_index_values(wi.index)
    for col in wi.columns:
        ax.plot(x, wi[col].astype(float).values, label=str(col))
    ax.set_title(f"Wealth index — {_join_symbols(pf, spec)} ({spec.ccy})")
    ax.set_ylabel(f"Wealth ({spec.ccy})")
    ax.legend()
    return _render(fig, save_path)


@translates_okama_errors
def plot_drawdowns(
    portfolio: dict[str, Any], width: int = 1500, height: int = 900, save_path: str | None = None
) -> Image | list[Image | str]:
    """Drawdown chart for the portfolio (percentage decline from previous peak).

    ``width``/``height``: PNG size in pixels (300-4000) for custom sizes/aspect ratios.
    ``save_path``: optional file path — also write the PNG there and report it
    (for clients that don't render MCP images inline, e.g. terminal clients).
    """
    spec, pf = _get_portfolio(portfolio)
    dd = pf.drawdowns.astype(float)
    fig, ax = make_figure(width, height)
    x = _plot_index_values(dd.index)
    ax.plot(x, dd.values, color="tab:red")
    ax.fill_between(x, dd.values, 0.0, color="tab:red", alpha=0.25)
    ax.set_title(f"Drawdowns — {_join_symbols(pf, spec)} ({spec.ccy})")
    ax.set_ylabel("Drawdown")
    return _render(fig, save_path)


@translates_okama_errors
def plot_efficient_frontier(
    frontier: dict[str, Any], width: int = 1500, height: int = 900, save_path: str | None = None
) -> Image | list[Image | str]:
    """Efficient-frontier curve (Risk vs Mean return) with individual asset points.

    ``width``/``height``: PNG size in pixels (300-4000) for custom sizes/aspect ratios.
    ``save_path``: optional file path — also write the PNG there and report it
    (for clients that don't render MCP images inline, e.g. terminal clients).
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
    ax.set_title(f"Efficient frontier — {_join_symbols(ef, spec)} ({spec.ccy})")
    ax.set_xlabel("Risk (annualized std)")
    ax.set_ylabel("Mean return (annualized)")
    ax.legend()
    return _render(fig, save_path)


@translates_okama_errors
def plot_monte_carlo(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    cashflow: dict[str, Any],
    width: int = 1500,
    height: int = 900,
    save_path: str | None = None,
) -> Image | list[Image | str]:
    """Monte Carlo forecast fan: percentile bands of future wealth over time.

    ``width``/``height``: PNG size in pixels (300-4000) for custom sizes/aspect ratios.
    ``save_path``: optional file path — also write the PNG there and report it
    (for clients that don't render MCP images inline, e.g. terminal clients).
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
    return _render(fig, save_path)


@translates_okama_errors
def plot_assets(
    symbols: list[str],
    ccy: str,
    first_date: str | None = None,
    last_date: str | None = None,
    inflation: bool = False,
    portfolios: list[dict[str, Any]] | None = None,
    width: int = 1500,
    height: int = 900,
    save_path: str | None = None,
) -> Image | list[Image | str]:
    """Wealth-index comparison chart for individual assets (growth of 1000 each).

    ``width``/``height``: PNG size in pixels (300-4000) for custom sizes/aspect ratios.
    ``save_path``: optional file path — also write the PNG there and report it
    (for clients that don't render MCP images inline, e.g. terminal clients).
    """
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)
    wi = al.wealth_indexes
    fig, ax = make_figure(width, height)
    x = _plot_index_values(wi.index)
    for col in wi.columns:
        ax.plot(x, wi[col].astype(float).values, label=str(col))
    ax.set_title(f"Wealth indexes — {', '.join(symbols)} ({ccy})")
    ax.set_ylabel(f"Wealth ({ccy})")
    ax.legend()
    return _render(fig, save_path)


@translates_okama_errors
def plot_irr_distribution(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    cashflow: dict[str, Any],
    width: int = 1500,
    height: int = 900,
    save_path: str | None = None,
) -> Image | list[Image | str]:
    """Histogram of money-weighted IRR across Monte Carlo scenarios.

    Shows the distribution of the investor's annualized return for the given
    cash-flow plan, with markers at the requested percentiles. Requires
    okama >= 2.2.0. ``width``/``height``: PNG size in pixels (300-4000);
    ``save_path``: optionally also write the PNG to a file and report the path.
    """
    pf, mc_spec = _prepare_dcf(portfolio, mc, cashflow)
    irr = pf.dcf.monte_carlo_irr().astype(float)

    fig, ax = make_figure(width, height)
    ax.hist(irr.values, bins=28, color="tab:blue", alpha=0.8, edgecolor="white")
    ymax = ax.get_ylim()[1]
    for p in sorted(mc_spec.percentiles):
        q = float(irr.quantile(p / 100.0))
        ax.axvline(q, color="#1e293b", linestyle="-" if p == 50 else ":",
                   linewidth=1.5, ymax=0.82)
        ax.annotate(f"p{p}\n{q:.1%}", (q, ymax * 0.84), ha="center", va="bottom",
                    fontsize=10, color="#1e293b")
    ax.set_ylim(0, ymax * 1.02)
    ax.set_title(
        f"IRR distribution — {mc_spec.scenarios} scenarios, "
        f"{mc_spec.period_years}y ({mc_spec.distribution})"
    )
    ax.set_xlabel("Money-weighted return (IRR)")
    ax.set_ylabel("Scenarios")
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    return _render(fig, save_path)


@translates_okama_errors
def plot_transition_map(
    frontier: dict[str, Any],
    x_axe: str = "risk",
    width: int = 1500,
    height: int = 900,
    save_path: str | None = None,
) -> Image | list[Image | str]:
    """Transition map: asset weights along the Efficient Frontier.

    ``x_axe`` is 'risk' or 'cagr' (the x-axis quantity). Rendered with the
    thread-safe OO matplotlib API from ``ef.ef_points`` (okama's own
    ``plot_transition_map`` uses global pyplot and is not used here).
    ``width``/``height``: PNG size in pixels (300-4000); ``save_path``: optionally
    also write the PNG and report the path.
    """
    if x_axe.lower() not in ("risk", "cagr"):
        raise OkamaMcpError("x_axe must be 'risk' or 'cagr'")
    spec, ef = _get_frontier(frontier)
    points = ef.ef_points
    x_col = "Risk" if x_axe.lower() == "risk" else "CAGR"
    fig, ax = make_figure(width, height)
    x = points[x_col].astype(float).values
    for col in points.columns:
        if col in _TM_NON_WEIGHT_COLS:
            continue
        ax.plot(x, points[col].astype(float).values, label=str(col))
    ax.set_xlim(float(points[x_col].min()), float(points[x_col].max()))
    ax.set_xlabel("Risk (volatility)" if x_col == "Risk" else "CAGR")
    ax.set_ylabel("Weights of assets")
    ax.set_title(f"Transition map — {_join_symbols(ef, spec)} ({spec.ccy})")
    ax.legend(loc="upper left")
    return _render(fig, save_path)


@translates_okama_errors
def plot_qq(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    width: int = 1500,
    height: int = 900,
    save_path: str | None = None,
) -> Image | list[Image | str]:
    """Q-Q plot of historical returns against the fitted MC distribution.

    The reference distribution is set by ``mc.distribution`` ('norm'/'lognorm'/'t')
    with parameters fitted from history (or overridden via ``distribution_parameters``).
    ``save_path``: also write the PNG there (for clients without inline images).
    """
    pf, mc_spec = _prepare_mc(portfolio, mc)
    ror = pf.dcf.mc.ror.astype(float)
    # Full fitted parameters (shape + loc + scale) so the plot honors any custom
    # distribution_parameters loc/scale, consistent with plot_hist_fit. The tuple
    # shape matches each distribution: norm=(mu, sigma); lognorm=(shape, loc, scale);
    # t=(df, loc, scale) — exactly what scipy's probplot sparams expects.
    params = pf.dcf.mc.get_parameters_for_distribution()
    fig, ax = make_figure(width, height)
    scipy.stats.probplot(ror.values, dist=mc_spec.distribution, sparams=tuple(params), plot=ax)
    ax.set_title(f"Q-Q plot vs {mc_spec.distribution} — {getattr(pf, 'symbol', 'portfolio')}")
    return _render(fig, save_path)


@translates_okama_errors
def plot_hist_fit(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    bins: int | None = None,
    width: int = 1500,
    height: int = 900,
    save_path: str | None = None,
) -> Image | list[Image | str]:
    """Histogram of historical returns with the fitted distribution PDF overlaid.

    The fitted curve is the ``mc.distribution`` density using parameters from
    history (or ``distribution_parameters``). ``bins``: histogram bin count.
    ``save_path``: also write the PNG there (for clients without inline images).
    """
    pf, mc_spec = _prepare_mc(portfolio, mc)
    ror = pf.dcf.mc.ror.astype(float)
    params = pf.dcf.mc.get_parameters_for_distribution()
    fig, ax = make_figure(width, height)
    ax.hist(ror.values, bins=bins if bins is not None else "auto", density=True, alpha=0.5,
            label="historical returns")
    x = np.linspace(float(ror.min()), float(ror.max()), 200)
    if mc_spec.distribution == "norm":
        pdf = scipy.stats.norm.pdf(x, loc=params[0], scale=params[1])
    elif mc_spec.distribution == "lognorm":
        pdf = scipy.stats.lognorm.pdf(x, params[0], loc=params[1], scale=params[2])
    else:  # t
        pdf = scipy.stats.t.pdf(x, df=params[0], loc=params[1], scale=params[2])
    ax.plot(x, pdf, color="tab:red", label=f"{mc_spec.distribution} fit")
    ax.set_title(f"Return distribution fit ({mc_spec.distribution}) — {getattr(pf, 'symbol', 'portfolio')}")
    ax.set_xlabel("Monthly return")
    ax.legend()
    return _render(fig, save_path)


def register(mcp: FastMCP) -> None:
    """Register chart tools with the FastMCP server."""
    mcp.tool(plot_wealth_index)
    mcp.tool(plot_drawdowns)
    mcp.tool(plot_efficient_frontier)
    mcp.tool(plot_transition_map)
    mcp.tool(plot_monte_carlo)
    mcp.tool(plot_assets)
    mcp.tool(plot_irr_distribution)
    mcp.tool(plot_qq)
    mcp.tool(plot_hist_fit)
