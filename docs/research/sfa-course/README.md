# SFA portfolio exercises: verified teaching snapshot

These are educational examples, not client recommendations. Calculations were
performed through local okama-mcp stdio on 18–19 October 2026 and preserved on
21 October. [Evidence](evidence.json) contains input specifications, tool replies,
monthly historical wealth for the distribution check, and numerical summaries.
The numbers are a dated snapshot, not a claim about the latest available data.

## Exercise 1: accumulation without contributions

Use SPY.US / AGG.US / GLD.US at 80% / 10% / 10%, USD, annual rebalancing,
January 2005 through December 2025. Start with USD 50,000, reinvest distributions,
and find the first month the portfolio reaches USD 100,000. Taxes and brokerage
fees are excluded throughout these exercises.

The first crossing is April 2014: USD 100,489 after 9 years 4 months; March was
USD 99,800. The choices are **3 / 9 / 20 years**, with **9** the nearest.
This is a historical first-passage calculation, not doubling at the full-window
CAGR: CAGR 10.26% gives approximately 7.1 years of hypothetical smooth growth.

Five alternative SPY / AGG / GLD allocations also select 9 among those choices:

| Weights | First crossing | Elapsed time |
|---|---|---|
| 70 / 20 / 10 | May 2014 | 9 years 5 months |
| 70 / 10 / 20 | October 2013 | 8 years 10 months |
| 80 / 15 / 5 | June 2014 | 9 years 6 months |
| 85 / 5 / 10 | March 2014 | 9 years 3 months |
| 90 / 5 / 5 | June 2014 | 9 years 6 months |

## Exercise 2: accumulation with indexed contributions

Keep the same history and allocations. Use USD 350 per month in the first year,
raising the monthly amount by 5% at each annual anniversary: USD 367.50 in year 2.
Use explicit dated `time_series` cash flows with
`time_series_discounted_values=false` for historical nominal payments. This
annual step schedule must not be silently replaced by monthly compounding.

| SPY / AGG / GLD | First crossing | Elapsed time |
|---|---|---|
| 80 / 10 / 10 | December 2010 | 6 years |
| 70 / 20 / 10 | December 2010 | 6 years |
| 70 / 10 / 20 | September 2010 | 5 years 9 months |
| 80 / 15 / 5 | January 2011 | 6 years 1 month |
| 85 / 5 / 10 | December 2010 | 6 years |
| 90 / 5 / 5 | February 2011 | 6 years 2 months |

The choices are **3 / 6 / 12 years**, with **6** nearest for all six allocations.
The principal portfolio ends December 2010 at USD 102,149. The original USD 100
contribution gave 7 years 3 months to 8 years 5 months; 8 was nearest among
3 / 8 / 15. A nearest-choice answer of 6 does not mean every portfolio meets a
strict six-year deadline. The largest calculated initial contribution needed
for that deadline across these allocations was about USD 386; USD 400 is a
rounded candidate for that stricter condition.

## Exercises 3 and 4: indexed withdrawals

Both exercises use RUB 10 million and annual rebalancing:

| Symbol | Weight |
|---|---:|
| RUCBTRNS.INDX | 40% |
| RGBITR.INDX | 20% |
| MCFTR.INDX | 25% |
| GC.COMM | 15% |

`GC.COM` is invalid; `search_assets` confirmed `GC.COMM` as Gold (COMEX),
USD-denominated and converted into the RUB portfolio by okama.

The user chose the maximum available common history for the forward model.
At the calculation date, the inflation-aligned portfolio resolved to
**January 2003–September 2026**, despite individual asset histories extending
into October. RUCBTRNS/RGBITR limit the start; inflation limits the end. No
monthly close was unchanged for more than two consecutive observations in the
checked asset histories. This is a flat-run check, not a comprehensive vendor
data-quality audit. No proxy was used.

Common forward assumptions:

- 25 years; 10,000 Monte Carlo scenarios; `random_seed=42`.
- Student-t monthly portfolio returns with parameters fitted from this history.
- `optimize_students_df(var_level=20)` minimizes squared historical VaR/CVaR
  errors for the lower 20% monthly-return tail, holding fitted location and scale
  fixed. It returned df **3.644179**; location and scale are recorded
  in the evidence rather than treated as permanent constants.
- Independently, the terminal/survival criterion uses **percentile 20**, i.e. an
  80% success target within the model. Tail calibration and the goal percentile
  are two different settings.
- `indexation` cash flows, `frequency="month"`, indexed at historical RUB
  inflation CAGR **0.08283419840827189**. The library compounds the annual rate
  into monthly increments; it does not simulate an independent inflation path.
- Positive amounts in the tables are initial monthly spending. The MCP input
  uses a negative `amount` for withdrawals.

| Exercise | Required outcome at 25 years | Initial monthly amount | Offered choices | Nearest answer |
|---|---|---:|---|---|
| 3 | Preserve the purchasing power of the initial RUB 10 million with 80% model probability | RUB 27,115.83 | A: 15k; B: 30k; C: 50k | B: 30k |
| 4 | Cover all withdrawals for 25 years with 80% model probability; no required terminal reserve | RUB 47,342.74 | A: 30k; B: 70k; C: 50k | C: 50k |

Exercise 3 uses `find_the_largest_withdrawals_size(goal="maintain_balance_pv")`
with horizon 25, percentile 20, relative tolerance 0.0001. Retaining real
RUB 10 million corresponds to roughly RUB **73.12 million nominal** after 25
years under the assumed inflation.

Exercise 4 first used `goal="survival_period"`, `target_survival_period=25`,
with a 26-year simulation because this library requires a longer simulation
horizon than the target survival period. That solver returned RUB 47,380.67.
A direct 25-year check found only **79.90%** survival at that amount. The final
amount above instead comes from a same-path search over all 300 monthly
withdrawals requiring at least 8,000 of 10,000 paths to remain positive. At
RUB 47,300, **80.11%** survive; at RUB 50,000, **73.30%** survive.

Dropping only a nominal RUB 10 million terminal reserve makes a much smaller
difference: the matched nominal-preservation amount was RUB 44,598.67. At this
inflation rate, nominal RUB 10 million in 25 years is only RUB 1.37 million of
initial purchasing power. Comparing that figure to a differently calibrated
older result is invalid.

## Why Student-t was chosen

On the earlier fixed January 2003–December 2025 diagnostic window, an expanding
annual refit used only preceding years and scored the following year during
2013–2025 (156 monthly observations). Lognormal location was fixed at -1;
normal mean/sample standard deviation and Student-t maximum-likelihood
parameters followed the library's conventions.

| Distribution | Mean held-out log score (higher is better) | Model mean return in worst 5% of months |
|---|---:|---:|
| Normal | 2.3801 | -4.03% |
| Lognormal | 2.3687 | -3.98% |
| Student-t | 2.4745 | -4.45% |
| Historical sample | — | -5.03% |

Student-t won the held-out score in 12 of 13 years against each alternative.
All three underestimated historical tail losses. These results support the
relative choice for monthly returns, not accuracy of 25-year forecasts. The
naive fitted-sample KS p-values are not treated as calibrated significance
levels. Optimizing df for the 20% tail was a subsequent user-selected calibration;
the fitted-distribution diagnostic is not proof that this optimization is
universally preferable or that the 2026 extension was separately validated.

## Reproduction and superseded intermediate figures

Call `analyze_portfolio` and verify actual dates. For a fresh forward-model run,
request the full available history, then pin the resolved dates in the saved
specification. Repeat fitting and calibration if history changes. Use explicit
weights, RUB, annual rebalancing and inflation enabled; apply identical resolved
parameters, seed and horizon when comparing objectives. See the
[indexed-withdrawal workflow](../../../.agents/skills/stress-testing-portfolios/references/indexed-withdrawals.md).

The evidence retains earlier norm/lognorm/t comparisons and December 2025
withdrawal calculations only as history. Their approximately RUB 41.7k normal,
RUB 47.3k fitted-t and RUB 46.3k optimized-t nominal-preservation outputs are
**superseded for the final exercises** by the matched September 2026 calibration
and the real-preservation/depletion objectives above. They must not be combined
into a new comparison.

Probabilities here are finite-sample model outputs, not guarantees. Real capital
preservation is a terminal objective; it does not prohibit interim drawdowns.
The model uses sampled monthly portfolio returns calibrated on an annually
rebalanced historical portfolio; it does not replay each asset and rebalance
its simulated path separately.
