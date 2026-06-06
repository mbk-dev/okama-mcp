"""IRR distribution chart for the announcement cover (EN version).

60/40 stocks/bonds (SPY/AGG, USD), CWD withdrawals — 4%/year of the
initial 10k indexed to inflation, cut during deep drawdowns.
Monte Carlo: norm, 20 years, 500 scenarios, seed 0.

Writes irr_cwd_distribution_en.png next to this file, where
announce-en.html picks it up. See README.md in this directory for the
full cover-regeneration flow.
"""

import os

os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np  # noqa: E402
import okama as ok  # noqa: E402

from okama_mcp.rendering import fig_to_png, make_figure  # noqa: E402

print(f"okama version: {ok.__version__}")

pf = ok.Portfolio(
    ["SPY.US", "AGG.US"],
    weights=[0.60, 0.40],
    ccy="USD",
    inflation=True,
    rebalancing_strategy=ok.Rebalance(period="year"),
    symbol="My_portfolio.PF",
)
cwd = ok.CutWithdrawalsIfDrawdown(
    parent=pf,
    initial_investment=10_000,
    frequency="year",
    amount=-400,  # 4% of the initial investment per year
    indexation="inflation",
)
pf.dcf.cashflow_parameters = cwd
np.random.seed(0)
pf.dcf.set_mc_parameters(distribution="norm", period=20, mc_number=500, seed=0)
irr = pf.dcf.monte_carlo_irr()

q05, q50, q95 = irr.quantile([0.05, 0.50, 0.95])
print(f"IRR quantiles: p5={q05:.2%}  median={q50:.2%}  p95={q95:.2%}")

fig, ax = make_figure(1200, 750)
ax.hist(irr.values, bins=28, color="#2563eb", alpha=0.8, edgecolor="white")
ymax = ax.get_ylim()[1]
labels = (
    (q05, f"p5\n{q05:.1%}", ":"),
    (q50, f"median\n{q50:.1%}", "-"),
    (q95, f"p95\n{q95:.1%}", ":"),
)
for q, label, style in labels:
    ax.axvline(q, color="#1e293b", linestyle=style, linewidth=1.5, ymax=0.82)
    ax.annotate(
        label, (q, ymax * 0.84), ha="center", va="bottom", fontsize=11, color="#1e293b",
        bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#cbd5e1"},
    )
ax.set_ylim(0, ymax * 1.02)
ax.set_title(
    "IRR distribution — Monte Carlo, 20 years, 500 scenarios\n"
    "60/40 stocks/bonds · 4%/yr withdrawals · cut in drawdowns (CWD)",
    fontsize=12.5,
)
ax.set_xlabel("Money-weighted rate of return (IRR)", fontsize=12)
ax.set_ylabel("Scenarios", fontsize=12)
ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")

out = os.path.join(os.path.dirname(__file__), "irr_cwd_distribution_en.png")
with open(out, "wb") as f:
    f.write(fig_to_png(fig))
print(f"saved: {out}")
