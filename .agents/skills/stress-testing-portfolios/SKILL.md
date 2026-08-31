---
name: stress-testing-portfolios
description: Use when backtesting or stress-testing an investment portfolio against macro shocks — currency devaluation, crisis episodes, inflation or rate regimes — or when the portfolio holds funds younger than the periods being tested, needs a proxy for missing history, or drives withdrawal, survival or tax conclusions.
---

# Stress-Testing Portfolios

## Overview

A stress test is only as good as the series underneath it. The wrong answers in
this work are rarely modelling errors — they are data defects and unit slips the
arithmetic absorbs silently: a history window that quietly shrank, a fund whose
price was frozen for two years, a nominal withdrawal measured against a real
portfolio value.

Run the mechanical gates first, then apply judgment. Both halves are below;
neither substitutes for the other.

## When to Use

- Backtesting a portfolio across crisis episodes (1998, 2008, 2014-16, 2022)
- Modelling a currency devaluation, inflation regime or rate shock forward
- Any portfolio holding funds (БПИФ/ETF) younger than the episodes tested
- Withdrawal sustainability, survival horizon or tax-consequence questions

Not for: single-asset return lookups, portfolio optimisation, or plain Monte Carlo
(call `monte_carlo_forecast` directly).

## Workflow

1. **Gate the data.**
   `poetry run python stress_test.py check SYM1 SYM2 ... --first 2010-02`
   Reports the binding history floor and every frozen price run. Do not walk past
   a finding — resolve it, or state it and its direction of bias in the report.
2. **If the episodes predate the floor, build a proxy** from long-history indices
   at the same weights, paired sleeve-to-sleeve.
3. **Validate the proxy on the overlap** — `stress_test.py validate`. Full window
   *and* each calendar year; an annual outlier is where the defects hide. An
   unvalidated proxy replay is not a result.
4. **Attribute every divergence to a named sleeve before explaining it** —
   `stress_test.py attribute --first ... --last ...`, one episode window at a time.
   The contributions must sum to the observed gap.
5. **Replay the episodes**, then calibrate scenario coefficients *from those
   episodes*.
6. **Run the forward scenarios** and report a range, not a point.

## Gates the Script Runs

| Gate | What it catches | Why it exists |
|---|---|---|
| History floor | okama truncates `first_date` to the intersection of all series, without raising or warning | `first_date=2010-02` on a basket containing LQDT.MOEX silently returns 2020-02 — 120 months shorter. A "2014-16 replay" would have been computed entirely on post-2020 data |
| Frozen series | runs of an unchanged monthly close | SBCB.MOEX sat at 1055.0 for 22 months (2022-02..2023-11: trading suspended, underlying eurobonds blocked), reading as a flat 0% return |
| Proxy validation | a proxy that does not track the actual | catches sleeve substitutions that drift |
| Gap attribution | a divergence explained by a story instead of a sleeve | the fact/proxy gap was first blamed on "the proxy runs hot"; per-sleeve attribution put the bulk of it on the frozen SBCB — the **fact understated**, the proxy did not overstate. Opposite sign, opposite conclusion |
| Rebalance thresholds | which threshold binds, per sleeve | see below |

**Attribution is per episode window, not per history.** Sleeve contributions are
buy-and-hold while the portfolios rebalance; over multi-year windows the
rebalancing path itself lands in the residual. On a single year the identity
closes to 0.00 p.p. and a residual really is an unfound cause.

## Judgment Rules

**A co-occurring shock is not a pass-through beta.** A beta is legitimate only
where the asset is mechanically linked to the factor — a USD-denominated holding
against the FX rate. In 2008 equities fell 61% while FX rose 52%; calling that a
beta of −1.16 and scaling it to a 200% devaluation manufactures an −80% equity leg
that nothing in the data supports. Fix crisis-specific shocks at a stated level
and say which episode the level came from.

**Never mix nominal and real inside one calculation.** Give them separate columns.
A survival table that shocked portfolio value in real terms while holding the
withdrawal nominal ranked a 200% devaluation as *better* than 100%.

**Track cost basis per sleeve, not portfolio-wide.** A forced sale hits one sleeve
at that sleeve's gain share; the portfolio-level share gives the wrong tax number.
Sleeves also differ in regime, not just in basis — for Russian portfolios see
project memory `gldrub-tom-tax-for-isp` (exchange gold is "иное имущество", not a
security, so п. 17.1 ст. 217 applies rather than ЛДВ).

**Read rebalancing semantics from the library, not from the parameter names.** In
okama's `Rebalance._check_if_rebalancing_required`, `abs_deviation` and
`rel_deviation` combine with **OR**, compare strictly (`>`), and **any single
asset** breaching rebalances the **whole** portfolio. The binding upper threshold
for a sleeve is `min(w + abs_dev, w × (1 + rel_dev))`: for a 5% sleeve at
`abs=10%, rel=50%` that is 7.5%, so one small volatile sleeve turns "conditional"
rebalancing into de-facto annual rebalancing. Count the events that actually
fired before describing the strategy.

**Include a control episode with no devaluation.** In the portfolio this skill was
built from, the worst real outcome (2022) was not a devaluation year — a
devaluation-only test would have reported the wrong worst case.

## okama Data Notes

| | |
|---|---|
| RUB inflation | `RUB.INFL` — `RUS.INFL` returns HTTP 404 |
| CBR key rate | `Rate("RUS_CBR.RATE")` returns **fractions** (0.11 = 11%); dividing by 100 turned a year of 11-13% rates into +0.1% |
| `AssetList.wealth_indexes` | carries an extra inflation column when `inflation=True` — select your symbols explicitly, never iterate the frame |
| PeriodIndex resampling | `resample("Y")`, not `"YE"` |
| Date range | `first_date` / `last_date` are requests, not guarantees — always read `.first_date` back |

## Report Contract

Every stress-test report carries these as their own slots:

1. The history window actually used, and what bound it.
2. Data defects found (frozen runs, suspensions) and the direction of their bias.
3. Proxy validation numbers, if a proxy was used.
4. Each scenario coefficient with the episode it was calibrated from.
5. Nominal and real results in separate columns.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Trusting the requested `first_date` | Run `check`; read `.first_date` back |
| Presenting a proxy replay without overlap numbers | Run `validate` first |
| Explaining a fact/proxy gap without attributing it | Run `attribute` per year; residual must close |
| Reading a long-window residual as a data defect | Re-run per calendar year — rebalancing path is in there |
| Scaling a crisis equity crash by devaluation size | Fix the level; betas only where mechanically linked |
| One "value" column mixing nominal and real | Split the columns |
