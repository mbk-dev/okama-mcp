# Design: expand okama-mcp with new okama methods + nested portfolios

Date: 2026-06-09
Status: approved (design), pending spec review

## Goal

Widen the MCP surface over the `okama` library with five high-value methods,
expose **all return metrics** of `okama.AssetList`, and add the ability to nest
a `Portfolio` as a component inside `AssetList`, `Portfolio`, and
`EfficientFrontier`.

All behaviour below is grounded in the installed okama 2.2.0 API (verified by
introspection and a live nesting test), not assumptions.

## Verified okama facts driving this design

- **Nesting:** `AssetList`, `Portfolio`, `EfficientFrontier` all accept
  `assets: list[Union[str, object]]`. An element is treated as "asset-like" when
  it has both `.symbol` and `.ror` (so a built `okama.Portfolio` qualifies). A
  live test confirmed nesting a `Portfolio` into all three works; the parent's
  `.symbols` then lists the nested portfolio's `.PF` symbol.
- **`EfficientFrontier.get_most_diversified_portfolio(target_return=None)`**
  returns a `dict`: `{asset_label: weight, ..., "CAGR", "Risk", "Diversification ratio"}`.
- **`PortfolioDCF.find_the_largest_withdrawals_size(goal, withdrawals_range=(0,1),
  target_survival_period=25, percentile=20, threshold=0, tolerance_rel=0.1,
  iter_max=20)`** returns a `Result(success, withdrawal_abs, withdrawal_rel,
  error_rel, solutions: DataFrame)` and requires `pf.dcf` to be configured first
  (cashflow strategy + MC parameters).
- **`EfficientFrontier.plot_transition_map(x_axe='risk')`** uses `plt.subplots()`
  (global pyplot) — **not thread-safe** under FastMCP worker threads. We will NOT
  call it. Instead we replicate its logic from `ef.ef_points` via the OO API
  (same approach already used by `plot_efficient_frontier`).
- **Benchmark metrics** (`index_beta`, `index_corr`,
  `tracking_difference_annualized`, `tracking_error`) treat the **first** symbol
  in the AssetList as the index/benchmark (documented in okama source).
- **Sharpe/Sortino:** `Portfolio.get_sharpe_ratio(rf_return=0) -> float`,
  `get_sortino_ratio(t_return=0) -> float`; the `AssetList` versions return a
  `Series` (per asset).
- **AssetList return metrics:** `get_cagr(period=None, real=False)`,
  `get_cumulative_return(period='YTD', real=False)`, `mean_return` (prop),
  `real_mean_return` (prop), `annual_return_ts` (prop),
  `get_rolling_cagr(window, real)`, `get_rolling_cumulative_return(window, real)`,
  `get_monthly_geometric_mean_return`.

## Decisions (resolved with the user)

1. **Nested portfolio representation:** recursive element — an `assets` entry is
   either a ticker string or a nested portfolio object. (Not a separate
   `portfolios` field on the specs.)
2. **AssetList-based tools:** keep the flat `symbols: list[str]` parameter and
   **add an optional `portfolios: list[dict]`** parameter. Backward compatible;
   existing calls and tests stay green.
3. **Return metrics packaging:** one `get_asset_returns` tool for scalar/since-
   inception metrics + one `get_rolling_returns` tool for the rolling series.

## Changes

### A. Schemas (`src/okama_mcp/schemas.py`)

- `PortfolioSpec.assets: list[str | PortfolioSpec]` (self-referential; call
  `PortfolioSpec.model_rebuild()` after class definition). `min_length=1`.
  - `_validate_weights`: `len(weights) == len(assets)` counts each top-level
    element (string or nested spec) as one. Non-negative, sum ≈ 1.0 unchanged.
- `FrontierSpec.assets: list[str | PortfolioSpec]`, `min_length=2`.
  - `_validate_bounds`: one `[min, max]` pair per top-level element (unchanged
    rule, now also covers nested elements).
- No `AssetListSpec` is introduced (decision 2).

Caching note: `make_key(spec.model_dump())` still works — `model_dump()` of a
nested spec is plain nested dicts (JSON-serialisable), so the content-hash cache
keys remain valid and stable.

### B. Builders

- **`portfolio.py`** — new `_resolve_assets(assets) -> list[str | ok.Portfolio]`:
  maps each element; `str` stays a string, a `PortfolioSpec` is built via
  `_build_portfolio(nested)`. `_build_portfolio` calls `_resolve_assets` on its
  own `spec.assets` (enables Portfolio-in-Portfolio, recursive).
- **`frontier.py`** — `_build_frontier` passes `_resolve_assets(spec.assets)` to
  `ok.EfficientFrontier`.
- **`asset_list.py`** — `_build_asset_list(symbols, ccy, first_date, last_date,
  inflation, portfolios=None)`: validate each `portfolios` dict via
  `PortfolioSpec`, build with `_build_portfolio`, append to `symbols`, pass the
  combined list to `ok.AssetList`. (Imports `_build_portfolio`/`PortfolioSpec`
  from `portfolio.py`/`schemas.py`; no circular import — `portfolio.py` does not
  import `asset_list.py`/`frontier.py`.)
- **Labels:** result label maps (`_weights_dict` and per-asset dicts) derive keys
  from the **built object's** `.symbols` (resolved), never from `spec.assets`
  (which may now contain dicts that are invalid as mapping keys).

Tools gaining the optional `portfolios: list[dict]` parameter (decision 2):
existing `compare_assets`, `get_correlations`, `get_rolling_risk`, and
`plot_assets`; plus the new `get_benchmark_metrics`, `get_asset_returns`,
`get_rolling_returns`. `get_dividend_info` is left unchanged (dividend streaks of
a nested portfolio are not meaningful).

### C. Item 1 — Sharpe / Sortino (no new tools)

- `analyze_portfolio(portfolio, rf_return=0.0, t_return=0.0)` adds output keys
  `sharpe_ratio` (`pf.get_sharpe_ratio(rf_return)`) and `sortino_ratio`
  (`pf.get_sortino_ratio(t_return)`).
- `compare_assets(symbols, ..., portfolios=None, rf_return=0.0, t_return=0.0)`
  adds `sharpe_ratio` and `sortino_ratio` (per-asset dicts from the Series).

### D. Item 2 — Most Diversified Portfolio (new tool, `frontier.py`)

- `get_most_diversified_portfolio(frontier: dict, target_return: float | None = None)`
  → `{weights: {...}, cagr, risk, diversification_ratio}`. Mirrors
  `get_tangency_portfolio` (split weight columns from the metric keys "CAGR",
  "Risk", "Diversification ratio").

### E. Item 3 — Benchmark metrics (new tool, `asset_list.py`)

- `get_benchmark_metrics(benchmark: str, symbols: list[str], ccy="USD",
  first_date=None, last_date=None, portfolios=None, rolling_window=None)`:
  builds `AssetList([benchmark, *symbols, *resolved_portfolios])` (benchmark
  first), returns the **latest** value per asset for `index_beta`, `index_corr`,
  `tracking_difference_annualized`, `tracking_error`. `rolling_window` is passed
  to the okama methods; the response still reports the last row to bound size.

### F. Item 4 — Transition map (new plot, `plots.py`)

- `plot_transition_map(frontier: dict, x_axe="risk", width_px=1500,
  height_px=900)`: get `ef` via `_get_frontier`; take `ef.ef_points`; x-axis =
  the `"Risk"` or `"CAGR"` column; for every column not in
  {`Risk`, `Mean return`, `CAGR`, `Weights`, `iterations`, `init_guess`} plot the
  weight line. Render via `make_figure`/`fig_to_png` (OO API). `x_axe` validated
  to `{"risk", "cagr"}`.

### G. Item 5 — Largest withdrawals size (new tool, `monte_carlo.py`)

- `find_the_largest_withdrawals_size(portfolio, mc, cashflow, goal,
  withdrawals_range=(0.0, 1.0), target_survival_period=25, percentile=20,
  threshold=0.0, tolerance_rel=0.1, iter_max=20)`:
  - `goal` ∈ {`maintain_balance_pv`, `maintain_balance_fv`, `survival_period`}.
  - Configure via `_prepare_dcf(portfolio, mc, cashflow)` (cashflow strategy +
    MC parameters), call the method, return
    `{success, withdrawal_abs, withdrawal_rel, error_rel, goal, n_evaluations}`.
  - Full `solutions` DataFrame is **not** returned (only `n_evaluations =
    solutions.shape[0]`).

### H. Return metrics (new tools, `asset_list.py`)

- `get_asset_returns(symbols, ccy="USD", first_date=None, last_date=None,
  inflation=True, portfolios=None, period=None, real=False)` →
  `{cagr, cumulative_return, mean_return, real_mean_return, monthly_geom_mean,
  annual_returns}` (each scalar metric a per-asset dict; `annual_returns` a
  per-year table, truncated if long).
- `get_rolling_returns(symbols, ccy="USD", window_months=12, real=False,
  first_date=None, last_date=None, portfolios=None)` →
  `{rolling_cagr, rolling_cumulative_return}` (DataFrames, serialised via
  `dataframe_to_json`).

### I. Registration

`tools/__init__.py` already calls each module's `register`. New tools are added
to their module's `register(mcp)`: `frontier` (+1), `asset_list` (+3),
`plots` (+1), `monte_carlo` (+1). Tool count **27 → 33**.

## Serialisation

Reuse `okama_mcp.serialization` (`series_to_json`, `dataframe_to_json`,
`value_to_json`) per project rule. Long series/frames truncated head/tail/summary
as the existing helpers do.

## Testing (TDD — mandatory, RED → GREEN → REFACTOR)

Follow the existing pattern: **unit tests mock okama at the boundary**
(`patch("okama_mcp.tools.<mod>.ok.AssetList"/".Portfolio"/".EfficientFrontier"`)
with `SimpleNamespace`/`MagicMock`; no network. Live tests go in
`tests/test_integration_live.py` (marker `integration`, skipped by default).

Per-area tests:
- **Schemas:** nested `PortfolioSpec`/`FrontierSpec` validate; weights length
  equals top-level element count (string + nested); invalid nested spec rejected.
- **Builders:** `_resolve_assets` turns a nested spec into an `ok.Portfolio`
  (mocked) and strings pass through; `_build_asset_list(portfolios=...)` appends
  built portfolios.
- **Each new tool:** one happy-path test asserting output keys/shape against a
  mocked okama object; `plot_transition_map` returns PNG bytes from a mocked
  `ef.ef_points`.
- **Enriched tools:** `analyze_portfolio`/`compare_assets` expose the new
  Sharpe/Sortino keys.

After code changes: `poetry run pytest -q` and `poetry run ruff check .` must be
clean (per AGENTS.md).

## Documentation (release rule)

- Update `README.md` tool catalogue (new tools, nesting capability).
- Sync the landing page `deploy/nginx/index.html` per the AGENTS.md release rule
  (teaser only: highlights/tool count, not a full catalogue mirror). Deploy +
  byte-diff verification happen at release time, not in this change.

## Out of scope (YAGNI)

- No `AssetListSpec` migration (flat params kept).
- No `QueryData.*` low-level wrappers (violates "don't re-implement api.okama.io
  calls").
- No `MonteCarlo` distribution-fitting tools, `plot_cml`/`plot_pair_ef`,
  `get_monte_carlo` cloud — deferred (lower value).
- `get_benchmark_metrics` returns latest values only, not full rolling series.
