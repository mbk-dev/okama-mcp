# Design: full MC / DCF / distribution parity for okama-mcp

Date: 2026-06-15
Status: approved (design), pending spec review

## Goal

Make the MCP a faithful mirror of okama's forecasting/DCF engine. Three asks:

1. Expose **all distribution parameters** for Monte Carlo (custom `(mu, sigma)` /
   `(shape, loc, scale)` / `(df, loc, scale)`, with `None` = fit from history).
2. Expose **all meaningful methods** of `okama.MonteCarlo` and
   `okama.PortfolioDCF` as tools.
3. Ensure **all CashFlow strategies** are available (already true — see below).

All behaviour below is grounded in the installed okama API (verified by reading
`okama/portfolios/mc.py`, `dcf.py`, `cashflow_strategies.py`, `common/validators.py`,
`settings.py`), not assumptions.

## Verified okama facts driving this design

- **`set_mc_parameters(distribution, distribution_parameters=None, period, mc_number, seed)`**
  (`dcf.py:143`) accepts `distribution_parameters` natively as a tuple or `None`.
- **`MonteCarlo.distribution_parameters`** structure (`mc.py:314-353`,
  `validate_distribution_parameters` in `common/validators.py`): `norm → (mu, sigma)`
  (len 2); `lognorm → (shape, loc, scale)` (len 3, loc fixed at -1 when fitted);
  `t → (df, loc, scale)` (len 3). Any element may be `None` → that element is fitted
  via `scipy.stats.<dist>.fit` (MLE). All-`None` or `None` arg → fully fitted.
- **Allowed distributions:** `okama.settings.distributions == ("norm", "lognorm", "t")`
  — byte-identical to the MCP schema `Distribution` literal.
- **MC diagnostics return shapes** (`mc.py`):
  - `get_parameters_for_distribution() -> tuple[float,...]` (fully resolved params).
  - `jarque_bera -> {"statistic", "p-value"}` (property).
  - `kstest -> {"statistic", "p-value"}` (property; uses current `distribution`).
  - `kstest_for_all_distributions -> DataFrame` indexed by the 3 distributions (small).
  - `backtesting_error(var_level=5) -> {"delta_arithmetic_mean", "delta_var", "delta_cvar"}`.
  - `optimize_df_for_students(var_level) -> float`; `var_level` must be in [1, 99].
  - `skewness` / `kurtosis` -> expanding `Series` over portfolio history (can be long).
  - `skewness_rolling(window=60)` / `kurtosis_rolling(window=60)` -> rolling `Series`
    (window must be ≥ 12 months per docstring).
  - `percentile_distribution_cagr(percentiles=[10,50,90]) -> {pct: value}` (runs MC).
  - `percentile_inverse_cagr(score=0) -> float` percentile rank (runs MC).
  - These diagnostics read `self.ror` (portfolio historical returns) and/or run MC;
    **none require a cashflow strategy**.
- **DCF method return shapes** (`dcf.py`):
  - `wealth_index(discounting, include_negative_values=False) -> DataFrame`
    (portfolio + accumulated inflation); historical; **requires cashflow**.
  - `cash_flow_ts(discounting, remove_if_wealth_index_negative=True) -> Series`;
    historical; requires cashflow.
  - `wealth_index_fv_with_assets -> DataFrame` (portfolio + each asset + inflation);
    historical; requires cashflow.
  - `survival_period_hist(threshold=0) -> float` (years); requires cashflow + discount_rate.
  - `survival_date_hist(threshold=0) -> Timestamp`; requires cashflow + discount_rate.
  - `initial_investment_pv -> float|None` (needs discount_rate); `initial_investment_fv -> float|None`.
  - `monte_carlo_cash_flow(discounting, remove_if_wealth_index_negative=True) -> DataFrame`
    months×scenarios (**huge** — summaries only).
  - `discount_rate` is a DCF property (used by all PV/survival paths).
- **Plots** (`mc.py`): `plot_qq(var_level=5, bootstrap_size_var=2000, zoom_to_left_tail=20, figsize=None)`,
  `plot_hist_fit(bins=None)`.

## Decisions (resolved with the user)

1. **Scope:** full parity — wrap every meaningful MC + DCF method. Skip pure
   setters (folded into specs) and the raw `monte_carlo_returns_ts` matrix.
2. **Raw matrices:** summaries only. `monte_carlo_cash_flow` is returned as
   percentile bands (reuse the existing summarizer), never the full matrix.
3. **Plots:** add `plot_qq` and `plot_hist_fit` as new PNG tools.
4. **Bundling:** tightly-related read-only scalars are grouped into cohesive tools
   (fit-stats suite; survival period+date; initial-investment pv+fv; the two CAGR
   percentile methods). Every method's output stays reachable.

## Changes

### A. Schemas (`src/okama_mcp/schemas.py`)

- **`MCSpec.distribution_parameters: list[float | None] | None = None`** with a
  `model_validator(mode="after")` that, when not `None`, enforces length per
  `distribution` (`norm` → 2, `lognorm`/`t` → 3) for a clean pre-okama error.
  okama still re-validates as a backstop.
- **`_CashflowBase.time_series_discounted_values: bool = False`** — close the last
  parity gap (PV-interpretation of `time_series` events). Wired in
  `_build_cashflow_strategy`.

### B. Shared helpers (`src/okama_mcp/tools/monte_carlo.py`)

- `_prepare_dcf(..., discount_rate: float | None = None)` — set
  `pf.dcf.discount_rate` only when provided.
- New `_prepare_mc(portfolio, mc) -> (pf, MCSpec)` — builds portfolio + calls
  `set_mc_parameters` (incl. `distribution_parameters`), **no cashflow**, for the
  diagnostics tools.
- `_prepare_dcf` also passes `distribution_parameters` into `set_mc_parameters`.

### C. New tools

**`src/okama_mcp/tools/mc_diagnostics.py`** (portfolio + mc; no cashflow):

1. `get_distribution_fit(portfolio, mc)` → `{distribution, parameters,
   jarque_bera, kstest, kstest_all_distributions, backtesting_error}`.
2. `get_return_moments(portfolio, mc, rolling_window=None)` → skewness & kurtosis
   series (expanding, or rolling when `rolling_window` given). Truncated.
3. `optimize_students_df(portfolio, mc, var_level=5)` → `{degrees_of_freedom}`.
4. `get_cagr_distribution(portfolio, mc, percentiles=[10,50,90], score=0.0)` →
   `{percentiles: {...}, prob_below_score, score}`.

**`src/okama_mcp/tools/dcf.py`** (portfolio + cashflow [+ discount_rate]):

5. `get_dcf_wealth_index(portfolio, cashflow, discounting="fv",
   include_negative_values=False, discount_rate=None)` → truncated series.
6. `get_dcf_cash_flow_ts(portfolio, cashflow, discounting="fv",
   remove_if_wealth_index_negative=True, discount_rate=None)` → truncated series.
7. `get_dcf_wealth_with_assets(portfolio, cashflow)` → truncated DataFrame.
8. `get_survival_period(portfolio, cashflow, threshold=0.0, discount_rate=None)`
   → `{survival_period_years, survival_date}`.
9. `get_initial_investment_values(portfolio, cashflow, discount_rate=None)`
   → `{pv, fv}`.
10. `get_monte_carlo_cash_flow(portfolio, mc, cashflow, discounting="fv")`
    → percentile-band summary (no raw matrix).

**`src/okama_mcp/tools/plots.py`**:

11. `plot_qq(portfolio, mc, var_level=5, zoom_to_left_tail=20, save_path=None)`.
12. `plot_hist_fit(portfolio, mc, bins=None, save_path=None)`.

Plot tools must avoid global `pyplot` in worker threads — follow the existing
`plots.py` pattern (explicit `Figure`/`Axes`, `MPLBACKEND=Agg`). If an okama plot
method uses global `plt.subplots`, replicate its drawing on an owned `Axes`
instead of calling it (same approach already used for `plot_transition_map`).

### D. Registration & docs

- Register all 12 in `src/okama_mcp/tools/__init__.py`.
- Update the README tool catalog. Version bump / `server.json` / landing-page sync
  are a **separate release step**, out of scope for this change.

## Serialization

- Time series (wealth index, cash flow, skewness, kurtosis) → existing
  head/tail/summary truncation in `okama_mcp.serialization`.
- `monte_carlo_cash_flow` → existing percentile-band summarizer used by
  `monte_carlo_forecast`. No new bulk-data path is introduced.

## Testing (TDD)

- **Offline unit tests** (no network): `MCSpec.distribution_parameters` length
  validation per distribution + `None` handling; `_CashflowBase` new flag; the
  percentile-band summary helper if any new logic is added.
- **Integration tests** behind the existing `integration` marker for the actual
  tool calls (they hit api.okama.io).
- Cycle per AGENTS.md: RED → verify RED → GREEN → verify GREEN → REFACTOR; run
  `poetry run pytest -q` and `poetry run ruff check .` before finishing.

## Out of scope

- Version bump, `server.json` tool list, mcp.okama.io landing sync (release step).
- Pure okama setters as standalone tools (config flows through specs).
- Raw `monte_carlo_returns_ts` / full MC matrices as tool output.

## Result

MCP tool count: 33 → 45. MC/DCF/CashFlow surface becomes a faithful mirror of
okama, including custom distribution parameters and goodness-of-fit diagnostics.
