"""Financial-plan forecast fan for the README and the landing page.

The plan is the one quoted in the example asks on https://mcp.okama.io/ and
at the top of the README: contribute $1,000/month for 20 years into a 70/30
portfolio (SPY/AGG, USD), then withdraw $6,000/month indexed to inflation
for 25 years out of the balance that accumulation produced.

Amounts are expressed in money of the plan's start: okama indexes a later
stage's cash flow forward from there, not from the stage's own first month.
At $6,000 even the p90 scenario runs dry, around year 19 of 25 — the point
of the chart is that a plan can fail late as well as early.

Rendered by calling the `plot_finplan_forecast` MCP tool itself, so the
picture is exactly what a client gets back. Deterministic given the data
(fixed seed), but live okama data evolves, so re-running moves the bands.

Writes finplan-forecast.png one directory up, next to the other README images.
"""

import os

os.environ.setdefault("MPLBACKEND", "Agg")

import pathlib  # noqa: E402

import okama as ok  # noqa: E402

from okama_mcp.tools.plots import plot_finplan_forecast  # noqa: E402

print(f"okama version: {ok.__version__}")

PORTFOLIO = {
    "assets": ["SPY.US", "AGG.US"],
    "weights": [0.7, 0.3],
    "ccy": "USD",
    "inflation": True,
    "rebalancing_strategy": {"period": "year"},
}

PLAN = {
    "name": "Retirement plan",
    "initial_investment": 10_000.0,
    "scenarios": 1000,
    "random_seed": 0,
    "percentiles": [10, 50, 90],
    "stages": [
        {
            "portfolio": PORTFOLIO,
            "period_years": 20,
            "name": "accumulation",
            "cashflow": {
                "type": "indexation",
                "initial_investment": 10_000.0,
                "frequency": "month",
                "amount": 1_000.0,
                "indexation": "inflation",
            },
        },
        {
            "portfolio": PORTFOLIO,
            "period_years": 25,
            "name": "retirement",
            "cashflow": {
                "type": "indexation",
                "initial_investment": 10_000.0,
                "frequency": "month",
                "amount": -6_000.0,
                "indexation": "inflation",
            },
        },
    ],
}

target = pathlib.Path(__file__).resolve().parent.parent / "finplan-forecast.png"
plot_finplan_forecast(plan=PLAN, width=1500, height=900, save_path=str(target))
print(f"wrote {target} ({target.stat().st_size} bytes)")
