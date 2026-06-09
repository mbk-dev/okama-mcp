# okama Method Expansion + Nested Portfolios — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 new okama-backed MCP tools, expose all `AssetList` return metrics, enrich `analyze_portfolio`/`compare_assets` with Sharpe/Sortino, and allow nesting a `Portfolio` as a component inside `AssetList`/`Portfolio`/`EfficientFrontier`.

**Architecture:** Thin stateless wrapper over `okama` 2.2.0. Specs are pydantic v2 models; each tool validates a spec, builds a (content-hash-cached) okama object, and serialises results via `okama_mcp.serialization`. Nesting reuses okama's native "mixed list" (`assets` may contain ticker strings or built `Portfolio` objects). Charts use the thread-safe OO matplotlib API (never okama's pyplot-based plot methods).

**Tech Stack:** Python 3.11, poetry, FastMCP, okama 2.2.0, pydantic v2, pandas, matplotlib (Agg), pytest, ruff.

**Design spec:** `docs/superpowers/specs/2026-06-09-okama-methods-expansion-design.md`

**Conventions (from AGENTS.md):**
- TDD mandatory: RED → verify RED → GREEN → verify GREEN → REFACTOR.
- After executable changes: `poetry run pytest -q`, then `poetry run ruff check .` — both clean.
- All comments/docstrings in English; type hints everywhere; f-strings for messages.
- Modern syntax: `list[...]`, `X | None`, literals over constructors.
- Tests mock okama at the boundary (`patch("okama_mcp.tools.<mod>.ok.<Class>")`); no network in unit tests. Live tests live in `tests/test_integration_live.py` (marker `integration`, skipped by default).
- **Commits are local only.** Do NOT `git push` — pushing requires explicit user confirmation (project commit policy).
- Run commands via the poetry env: `poetry run pytest ...`, `poetry run ruff ...`.

---

## Verified okama facts (do not re-derive)

- Nesting: `AssetList`/`Portfolio`/`EfficientFrontier` accept `assets: list[str | object]`; an element counts as asset-like if it has `.symbol` and `.ror` (a built `okama.Portfolio` qualifies). Confirmed live.
- `EfficientFrontier.get_most_diversified_portfolio(target_return=None)` → `dict` `{asset: weight, ..., "CAGR", "Risk", "Diversification ratio"}`.
- `PortfolioDCF.find_the_largest_withdrawals_size(goal, withdrawals_range=(0,1), target_survival_period=25, percentile=20, threshold=0, tolerance_rel=0.1, iter_max=20)` → `Result(success, withdrawal_abs, withdrawal_rel, error_rel, solutions: DataFrame)`; requires `pf.dcf` configured first.
- `EfficientFrontier.plot_transition_map` uses global `plt` — NOT thread-safe; replicate from `ef.ef_points` via OO API.
- Benchmark metrics treat the FIRST AssetList symbol as the index.
- `AssetList.get_sharpe_ratio(rf_return=0)` / `get_sortino_ratio(t_return=0)` → `Series`; `Portfolio` versions → `float`.
- AssetList return-metric shapes (live-verified):
  - `get_cagr(period=None, real=False)` → **DataFrame** expanding series (cols = assets [+ inflation]); since-inception = last row.
  - `get_cumulative_return(period=None, real=False)` → **DataFrame** expanding series; total = last row.
  - `mean_return`, `real_mean_return` → **Series** (per asset, no inflation).
  - `get_monthly_geometric_mean_return()` → **Series** (per asset).
  - `annual_return_ts` → **DataFrame** (years × assets).
  - `get_rolling_cagr(window, real)`, `get_rolling_cumulative_return(window, real)` → **DataFrame** time series.

---

## File map

- `src/okama_mcp/schemas.py` — recursive `PortfolioSpec`/`FrontierSpec` `assets`.
- `src/okama_mcp/tools/portfolio.py` — `_resolve_assets`, nested `_build_portfolio`, label fix in `_weights_dict`, Sharpe/Sortino in `analyze_portfolio`.
- `src/okama_mcp/tools/frontier.py` — nested `_build_frontier`, new `get_most_diversified_portfolio`.
- `src/okama_mcp/tools/asset_list.py` — `_build_asset_list(portfolios=...)`, `portfolios` on existing tools, Sharpe/Sortino in `compare_assets`, new `get_benchmark_metrics`, `get_asset_returns`, `get_rolling_returns`.
- `src/okama_mcp/tools/plots.py` — nesting-safe titles, new `plot_transition_map`, `portfolios` on `plot_assets`.
- `src/okama_mcp/tools/monte_carlo.py` — new `find_the_largest_withdrawals_size`.
- Tests mirror each module under `tests/`.
- `README.md`, `deploy/nginx/index.html` — docs sync.

---

## Task 1: Recursive nested specs (schemas)

**Files:**
- Modify: `src/okama_mcp/schemas.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_schemas.py` (extend the import line to include `FrontierSpec`):

```python
class TestNestedSpecs:
    def test_portfolio_accepts_nested_portfolio(self) -> None:
        spec = PortfolioSpec(
            assets=["GLD.US", {"assets": ["SPY.US", "AGG.US"], "weights": [0.6, 0.4], "symbol": "b.PF"}],
            weights=[0.3, 0.7],
        )
        assert isinstance(spec.assets[1], PortfolioSpec)
        assert spec.assets[1].symbol == "b.PF"

    def test_weights_count_top_level_elements(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSpec(
                assets=["GLD.US", {"assets": ["A", "B"], "weights": [0.5, 0.5]}],
                weights=[0.3, 0.3, 0.4],
            )

    def test_invalid_nested_spec_rejected(self) -> None:
        # nested weights do not sum to 1.0 -> nested validator fires
        with pytest.raises(ValidationError):
            PortfolioSpec(assets=[{"assets": ["A", "B"], "weights": [0.5, 0.3]}])

    def test_frontier_accepts_nested_portfolio(self) -> None:
        spec = FrontierSpec(assets=["GLD.US", {"assets": ["SPY.US", "AGG.US"]}])
        assert isinstance(spec.assets[1], PortfolioSpec)
        assert spec.assets[0] == "GLD.US"
```

Update the import at the top of the file:

```python
from okama_mcp.schemas import (
    CashflowAdapter,
    CutIfDrawdownCashflow,
    FrontierSpec,
    IndexationCashflow,
    MCSpec,
    PercentageCashflow,
    PortfolioSpec,
    TimeSeriesCashflow,
    VanguardDynamicCashflow,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_schemas.py::TestNestedSpecs -q`
Expected: FAIL (nested dict not coerced to `PortfolioSpec`; `isinstance` is False).

- [ ] **Step 3: Implement recursive `assets`**

In `src/okama_mcp/schemas.py`, change `PortfolioSpec.assets`:

```python
    assets: list[str | "PortfolioSpec"] = Field(
        min_length=1,
        description=(
            "Assets: each entry is a ticker string (e.g. 'GLD.US') OR a nested "
            "portfolio object (same shape as this spec) used as a single component."
        ),
    )
```

Immediately after the `PortfolioSpec` class (after its `_validate_weights` method) add:

```python
PortfolioSpec.model_rebuild()
```

Change `FrontierSpec.assets`:

```python
    assets: list[str | PortfolioSpec] = Field(
        min_length=2,
        description=(
            "At least two entries; each is a ticker string OR a nested portfolio "
            "object used as a single component."
        ),
    )
```

(The existing `_validate_weights` length check and `_validate_bounds` length check already count each top-level element as one — no change needed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_schemas.py -q`
Expected: PASS (all schema tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): allow nested portfolio objects in PortfolioSpec/FrontierSpec assets"
```

---

## Task 2: Builders resolve nested portfolios (portfolio + frontier)

**Files:**
- Modify: `src/okama_mcp/tools/portfolio.py`
- Modify: `src/okama_mcp/tools/frontier.py`
- Test: `tests/test_tool_portfolio.py`, `tests/test_tool_frontier.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tool_portfolio.py`:

```python
def test_resolve_assets_builds_nested_portfolio() -> None:
    from okama_mcp.schemas import PortfolioSpec

    spec = PortfolioSpec(
        assets=["GLD.US", {"assets": ["A.US", "B.US"], "weights": [0.6, 0.4]}],
        weights=[0.3, 0.7],
    )
    with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value="PFOBJ"), \
         patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
        resolved = pf_tool._resolve_assets(spec.assets)
    assert resolved == ["GLD.US", "PFOBJ"]
```

Also add a `_weights_dict` nesting test to `tests/test_tool_portfolio.py` (labels must come from `pf.symbols`, not `spec.assets`, which now holds a nested model):

```python
def test_weights_dict_labels_from_pf_symbols_under_nesting() -> None:
    from types import SimpleNamespace as NS
    from okama_mcp.schemas import PortfolioSpec

    spec = PortfolioSpec(
        assets=["GLD.US", {"assets": ["A.US", "B.US"], "weights": [0.6, 0.4], "symbol": "b.PF"}],
        weights=[0.3, 0.7],
    )
    pf = NS(symbols=["GLD.US", "b.PF"], weights=[0.3, 0.7])
    assert pf_tool._weights_dict(pf, spec) == {"GLD.US": 0.3, "b.PF": 0.7}
```

Add to `tests/test_tool_frontier.py`:

```python
def test_build_frontier_resolves_nested_portfolio() -> None:
    from okama_mcp.schemas import FrontierSpec

    spec = FrontierSpec(assets=["GLD.US", {"assets": ["A.US", "B.US"]}])
    with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value="PFOBJ"), \
         patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"), \
         patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"), \
         patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value="EF") as efmock:
        fr_tool._build_frontier(spec)
    assert efmock.call_args.kwargs["assets"] == ["GLD.US", "PFOBJ"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_tool_portfolio.py::test_resolve_assets_builds_nested_portfolio tests/test_tool_portfolio.py::test_weights_dict_labels_from_pf_symbols_under_nesting tests/test_tool_frontier.py::test_build_frontier_resolves_nested_portfolio -q`
Expected: FAIL (`_resolve_assets` undefined; `_build_frontier` passes raw dicts). The `_weights_dict` test may currently pass if `pf.symbols` is already used — if it fails, the label fix below makes it pass.

- [ ] **Step 3: Implement `_resolve_assets` + nested builders**

In `src/okama_mcp/tools/portfolio.py`, add `_resolve_assets` just above `_build_portfolio` and use it inside `_build_portfolio`:

```python
def _resolve_assets(assets: list[Any]) -> list[Any]:
    """Map a spec assets list to okama-ready elements.

    A ticker string passes through unchanged; a nested ``PortfolioSpec`` is built
    into an ``okama.Portfolio`` object, which okama accepts as an asset-like
    component (it has ``.symbol`` and ``.ror``).
    """
    resolved: list[Any] = []
    for item in assets:
        if isinstance(item, PortfolioSpec):
            resolved.append(_build_portfolio(item))
        else:
            resolved.append(item)
    return resolved
```

Change the `assets=` argument inside `_build_portfolio`:

```python
    return ok.Portfolio(
        assets=_resolve_assets(spec.assets),
        weights=list(spec.weights) if spec.weights is not None else None,
        ccy=spec.ccy,
        first_date=spec.first_date,
        last_date=spec.last_date,
        inflation=spec.inflation,
        rebalancing_strategy=rebalance,
        symbol=spec.symbol,
    )
```

Also update `_weights_dict` in `src/okama_mcp/tools/portfolio.py` so labels come from the built object's resolved `.symbols` (under nesting `spec.assets` holds an unhashable nested model and must not be used as dict keys):

```python
def _weights_dict(pf: Any, spec: PortfolioSpec) -> dict[str, float]:
    # Avoid `or` chains — Portfolio.weights may be a numpy array, whose truth
    # value is ambiguous. Pick the first non-None source explicitly.
    pf_weights = getattr(pf, "weights", None)
    if pf_weights is not None:
        weights = list(pf_weights)
    elif spec.weights is not None:
        weights = list(spec.weights)
    else:
        n = len(spec.assets)
        weights = [1.0 / n] * n
    # Labels come from the resolved symbols (a nested portfolio contributes its
    # .PF symbol); spec.assets may contain nested specs that are not valid keys.
    syms = getattr(pf, "symbols", None)
    labels = list(syms) if syms is not None else [a for a in spec.assets if isinstance(a, str)]
    return {str(symbol): value_to_json(w) for symbol, w in zip(labels, weights, strict=False)}
```

In `src/okama_mcp/tools/frontier.py`, add the import near the other tool imports:

```python
from okama_mcp.tools.portfolio import _resolve_assets
```

Change the `assets=` argument inside `_build_frontier`:

```python
    return ok.EfficientFrontier(
        assets=_resolve_assets(spec.assets),
        ccy=spec.ccy,
        first_date=spec.first_date,
        last_date=spec.last_date,
        bounds=_bounds_for_okama(spec.bounds),
        inflation=spec.inflation,
        full_frontier=spec.full_frontier,
        n_points=spec.n_points,
        rebalancing_strategy=ok.Rebalance(
            period=spec.rebalancing_strategy.period,
            abs_deviation=spec.rebalancing_strategy.abs_deviation,
            rel_deviation=spec.rebalancing_strategy.rel_deviation,
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_tool_portfolio.py tests/test_tool_frontier.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/portfolio.py src/okama_mcp/tools/frontier.py tests/test_tool_portfolio.py tests/test_tool_frontier.py
git commit -m "feat(tools): build nested portfolios into Portfolio and EfficientFrontier"
```

---

## Task 3: AssetList builder + `portfolios` on existing tools

**Files:**
- Modify: `src/okama_mcp/tools/asset_list.py`
- Test: `tests/test_tool_asset_list.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tool_asset_list.py`:

```python
def test_build_asset_list_appends_nested_portfolio() -> None:
    with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value="PFOBJ"), \
         patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"), \
         patch("okama_mcp.tools.asset_list.ok.AssetList", return_value="AL") as almock:
        al_tool._build_asset_list(
            ["GLD.US"], "USD", None, None, False,
            portfolios=[{"assets": ["A.US", "B.US"], "weights": [0.6, 0.4], "symbol": "b.PF"}],
        )
    assert almock.call_args.args[0] == ["GLD.US", "PFOBJ"]


def test_compare_assets_passes_portfolios_through() -> None:
    describe = pd.DataFrame({"GLD.US": [0.08], "b.PF": [0.07]}, index=["CAGR"])
    ror = pd.DataFrame({"GLD.US": [0.01], "b.PF": [0.02]},
                       index=pd.period_range("2024-01", periods=1, freq="M"))
    mock = _make_asset_list_mock(describe_df=describe, ror_df=ror, symbols=["GLD.US", "b.PF"])
    with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value="PFOBJ"), \
         patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"), \
         patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock) as almock:
        out = al_tool.compare_assets(
            ["GLD.US"], ccy="USD",
            portfolios=[{"assets": ["A.US", "B.US"], "weights": [0.6, 0.4], "symbol": "b.PF"}],
        )
    assert almock.call_args.args[0] == ["GLD.US", "PFOBJ"]
    assert out["symbols"] == ["GLD.US", "b.PF"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_tool_asset_list.py::test_build_asset_list_appends_nested_portfolio tests/test_tool_asset_list.py::test_compare_assets_passes_portfolios_through -q`
Expected: FAIL (`_build_asset_list` has no `portfolios` kwarg; `compare_assets` has no `portfolios` param).

- [ ] **Step 3: Implement builder + wire tools**

In `src/okama_mcp/tools/asset_list.py`, update imports:

```python
from pydantic import ValidationError

from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.schemas import PortfolioSpec
from okama_mcp.serialization import dataframe_to_json, value_to_json
from okama_mcp.tools.portfolio import _build_portfolio
```

Replace `_build_asset_list` with:

```python
def _build_asset_list(
    symbols: list[str],
    ccy: str,
    first_date: str | None,
    last_date: str | None,
    inflation: bool,
    portfolios: list[dict[str, Any]] | None = None,
) -> Any:
    resolved: list[Any] = list(symbols)
    for raw in portfolios or []:
        try:
            p_spec = PortfolioSpec.model_validate(raw)
        except ValidationError as exc:
            raise OkamaMcpError(f"Invalid portfolio spec: {exc.errors()}") from exc
        resolved.append(_build_portfolio(p_spec))
    if not resolved:
        raise OkamaMcpError("symbols must be a non-empty list of okama tickers")
    return ok.AssetList(
        resolved,
        ccy=ccy,
        first_date=first_date,
        last_date=last_date,
        inflation=inflation,
    )
```

Add a `portfolios` parameter (default `None`) to `compare_assets`, `get_correlations`, and `get_rolling_risk`, and pass it through to `_build_asset_list`. Concretely:

`compare_assets` signature and build call become:

```python
def compare_assets(
    symbols: list[str],
    ccy: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    inflation: bool = True,
    portfolios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ...
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)
```

`get_correlations` signature and build call:

```python
def get_correlations(
    symbols: list[str],
    ccy: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    inflation: bool = True,
    portfolios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ...
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)
```

`get_rolling_risk` signature and build call:

```python
def get_rolling_risk(
    symbols: list[str],
    ccy: str,
    window_months: int = 12,
    first_date: str | None = None,
    last_date: str | None = None,
    portfolios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ...
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation=False, portfolios=portfolios)
```

Also update each tool's docstring with a one-line note: "`portfolios`: optional list of portfolio specs to include as components alongside `symbols`."

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_tool_asset_list.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/asset_list.py tests/test_tool_asset_list.py
git commit -m "feat(asset_list): accept nested portfolios in compare/correlations/rolling-risk"
```

---

## Task 4: Sharpe / Sortino in analyze_portfolio + compare_assets

**Files:**
- Modify: `src/okama_mcp/tools/portfolio.py`
- Modify: `src/okama_mcp/tools/asset_list.py`
- Test: `tests/test_tool_portfolio.py`, `tests/test_tool_asset_list.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_tool_portfolio.py`, extend `_make_portfolio_mock` to provide the two methods (add after `pf.percentile_inverse_cagr = ...`):

```python
    pf.get_sharpe_ratio = MagicMock(return_value=0.42)
    pf.get_sortino_ratio = MagicMock(return_value=0.55)
```

Add a test:

```python
class TestAnalyzePortfolioRiskAdjusted:
    def test_includes_sharpe_and_sortino(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.analyze_portfolio(VALID_SPEC, rf_return=0.02, t_return=0.0)
        assert out["metrics"]["sharpe_ratio"] == 0.42
        assert out["metrics"]["sortino_ratio"] == 0.55
        pf.get_sharpe_ratio.assert_called_once_with(rf_return=0.02)
        pf.get_sortino_ratio.assert_called_once_with(t_return=0.0)
```

In `tests/test_tool_asset_list.py`, extend `_make_asset_list_mock` (add before `return mock`):

```python
    mock.get_sharpe_ratio = MagicMock(return_value=pd.Series({s: 0.4 for s in symbols}))
    mock.get_sortino_ratio = MagicMock(return_value=pd.Series({s: 0.5 for s in symbols}))
```

Add a test:

```python
class TestCompareAssetsRiskAdjusted:
    def test_includes_sharpe_and_sortino(self) -> None:
        describe = pd.DataFrame({"GLD.US": [0.08], "VNQ.US": [0.07]}, index=["CAGR"])
        ror = pd.DataFrame({"GLD.US": [0.01], "VNQ.US": [0.02]},
                           index=pd.period_range("2024-01", periods=1, freq="M"))
        mock = _make_asset_list_mock(describe_df=describe, ror_df=ror, symbols=["GLD.US", "VNQ.US"])
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock):
            out = al_tool.compare_assets(["GLD.US", "VNQ.US"], ccy="USD")
        assert out["sharpe_ratio"] == {"GLD.US": 0.4, "VNQ.US": 0.4}
        assert out["sortino_ratio"] == {"GLD.US": 0.5, "VNQ.US": 0.5}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_tool_portfolio.py::TestAnalyzePortfolioRiskAdjusted tests/test_tool_asset_list.py::TestCompareAssetsRiskAdjusted -q`
Expected: FAIL (keys absent; params absent).

- [ ] **Step 3: Implement**

In `src/okama_mcp/tools/portfolio.py`, change `analyze_portfolio` signature and the `metrics` block:

```python
@translates_okama_errors
def analyze_portfolio(
    portfolio: dict[str, Any],
    rf_return: float = 0.0,
    t_return: float = 0.0,
) -> dict[str, Any]:
    """Backtest summary for a portfolio: CAGR, risk, drawdowns, describe table.

    ``rf_return`` is the risk-free rate for the Sharpe ratio; ``t_return`` the
    target return for the Sortino ratio. ``portfolio`` must match
    :class:`PortfolioSpec` (``assets`` entries may be tickers or nested portfolio
    objects).
    """
    spec, pf = _get_portfolio(portfolio)
    return {
        "spec": spec.model_dump(),
        "weights": _weights_dict(pf, spec),
        "ccy": getattr(pf, "currency", spec.ccy),
        "first_date": value_to_json(getattr(pf, "first_date", None)),
        "last_date": value_to_json(getattr(pf, "last_date", None)),
        "period_years": value_to_json(getattr(pf, "period_length", None)),
        "metrics": {
            "cagr": _scalar_cagr(pf),
            "mean_return_annual": value_to_json(
                _scalar_last(getattr(pf, "mean_return_annual", None))
            ),
            "risk_annual": value_to_json(_scalar_last(getattr(pf, "risk_annual", None))),
            "sharpe_ratio": value_to_json(float(pf.get_sharpe_ratio(rf_return=rf_return))),
            "sortino_ratio": value_to_json(float(pf.get_sortino_ratio(t_return=t_return))),
        },
        "describe": dataframe_to_json(pf.describe()),
    }
```

In `src/okama_mcp/tools/asset_list.py`, change `compare_assets` to compute and include the two per-asset dicts. Add params `rf_return: float = 0.0, t_return: float = 0.0` to the signature (after `portfolios`), and build the return dict like:

```python
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)
    desc = al.describe()
    sharpe = al.get_sharpe_ratio(rf_return=rf_return)
    sortino = al.get_sortino_ratio(t_return=t_return)
    return {
        "symbols": list(getattr(al, "symbols", symbols)),
        "ccy": getattr(al, "currency", ccy),
        "first_date": value_to_json(getattr(al, "first_date", None)),
        "last_date": value_to_json(getattr(al, "last_date", None)),
        "describe": dataframe_to_json(desc),
        "sharpe_ratio": {str(k): value_to_json(v) for k, v in sharpe.items()},
        "sortino_ratio": {str(k): value_to_json(v) for k, v in sortino.items()},
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_tool_portfolio.py tests/test_tool_asset_list.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/portfolio.py src/okama_mcp/tools/asset_list.py tests/test_tool_portfolio.py tests/test_tool_asset_list.py
git commit -m "feat(tools): add Sharpe/Sortino to analyze_portfolio and compare_assets"
```

---

## Task 5: Most Diversified Portfolio (frontier)

**Files:**
- Modify: `src/okama_mcp/tools/frontier.py`
- Test: `tests/test_tool_frontier.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_tool_frontier.py`, extend `_make_ef_mock` (add before `return ef`):

```python
    ef.get_most_diversified_portfolio = MagicMock(
        return_value={
            "SPY.US": 0.30, "GLD.US": 0.30, "BND.US": 0.40,
            "CAGR": 0.071, "Risk": 0.092, "Diversification ratio": 1.42,
        }
    )
```

Add a test:

```python
class TestMostDiversifiedPortfolio:
    def test_returns_weights_and_metrics(self) -> None:
        ef = _make_ef_mock()
        with patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef), \
             patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"):
            out = fr_tool.get_most_diversified_portfolio(
                {"assets": ["SPY.US", "GLD.US", "BND.US"], "ccy": "USD"}
            )
        assert out["weights"] == {"SPY.US": 0.30, "GLD.US": 0.30, "BND.US": 0.40}
        assert out["cagr"] == 0.071
        assert out["risk"] == 0.092
        assert out["diversification_ratio"] == 1.42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_tool_frontier.py::TestMostDiversifiedPortfolio -q`
Expected: FAIL (`get_most_diversified_portfolio` undefined).

- [ ] **Step 3: Implement**

In `src/okama_mcp/tools/frontier.py`, add a module constant near the top (after imports) and the tool before `register`:

```python
_MDP_METRIC_KEYS = ("CAGR", "Risk", "Diversification ratio")
```

```python
@translates_okama_errors
def get_most_diversified_portfolio(
    frontier: dict[str, Any],
    target_return: float | None = None,
) -> dict[str, Any]:
    """Most Diversified Portfolio (MDP) on the Efficient Frontier.

    Maximises the diversification ratio (weighted average asset volatility over
    portfolio volatility). Optionally constrained to a ``target_return`` (CAGR).
    Returns the asset weights plus the portfolio CAGR, Risk, and diversification
    ratio. ``frontier`` is a :class:`FrontierSpec` dict.
    """
    spec, ef = _get_frontier(frontier)
    raw = ef.get_most_diversified_portfolio(target_return=target_return)
    weights = {
        str(k): value_to_json(float(v))
        for k, v in raw.items()
        if k not in _MDP_METRIC_KEYS
    }
    return {
        "weights": weights,
        "cagr": value_to_json(float(raw["CAGR"])),
        "risk": value_to_json(float(raw["Risk"])),
        "diversification_ratio": value_to_json(float(raw["Diversification ratio"])),
        "target_return": value_to_json(target_return),
    }
```

Add to `register`:

```python
    mcp.tool(get_most_diversified_portfolio)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_tool_frontier.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/frontier.py tests/test_tool_frontier.py
git commit -m "feat(frontier): add get_most_diversified_portfolio tool"
```

---

## Task 6: Benchmark metrics (asset_list)

**Files:**
- Modify: `src/okama_mcp/tools/asset_list.py`
- Test: `tests/test_tool_asset_list.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tool_asset_list.py`:

```python
class TestBenchmarkMetrics:
    def test_returns_latest_beta_corr_tracking(self) -> None:
        idx = pd.period_range("2024-01", periods=2, freq="M")
        beta = pd.DataFrame({"GLD.US": [0.9, 0.95]}, index=idx)
        corr = pd.DataFrame({"GLD.US": [0.7, 0.72]}, index=idx)
        td = pd.DataFrame({"GLD.US": [0.01, 0.012]}, index=idx)
        te = pd.DataFrame({"GLD.US": [0.05, 0.048]}, index=idx)
        mock = SimpleNamespace()
        mock.symbols = ["SP500TR.INDX", "GLD.US"]
        mock.currency = "USD"
        mock.index_beta = MagicMock(return_value=beta)
        mock.index_corr = MagicMock(return_value=corr)
        mock.tracking_difference_annualized = MagicMock(return_value=td)
        mock.tracking_error = MagicMock(return_value=te)
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock) as m:
            out = al_tool.get_benchmark_metrics("SP500TR.INDX", ["GLD.US"], ccy="USD")
        # benchmark must be first in the AssetList
        assert m.call_args.args[0] == ["SP500TR.INDX", "GLD.US"]
        assert out["benchmark"] == "SP500TR.INDX"
        assert out["beta"] == {"GLD.US": 0.95}
        assert out["correlation"] == {"GLD.US": 0.72}
        assert out["tracking_difference_annualized"] == {"GLD.US": 0.012}
        assert out["tracking_error"] == {"GLD.US": 0.048}

    def test_empty_benchmark_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            al_tool.get_benchmark_metrics("", ["GLD.US"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_tool_asset_list.py::TestBenchmarkMetrics -q`
Expected: FAIL (`get_benchmark_metrics` undefined).

- [ ] **Step 3: Implement**

In `src/okama_mcp/tools/asset_list.py`, add before `register`:

```python
@translates_okama_errors
def get_benchmark_metrics(
    benchmark: str,
    symbols: list[str],
    ccy: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    portfolios: list[dict[str, Any]] | None = None,
    rolling_window: int | None = None,
) -> dict[str, Any]:
    """Metrics of each asset relative to a benchmark/index.

    Builds an AssetList with ``benchmark`` first (okama treats the first symbol as
    the index), then ``symbols`` and any nested ``portfolios``. Returns the latest
    value per asset of: beta, correlation with the index, annualized tracking
    difference, and tracking error. ``rolling_window`` (months, >= 12) switches
    okama to a moving window; the response still reports the most recent row.
    """
    if not benchmark:
        raise OkamaMcpError("benchmark must be a non-empty okama ticker")
    al = _build_asset_list(
        [benchmark, *symbols], ccy, first_date, last_date, inflation=False, portfolios=portfolios
    )

    def _last_row(df: Any) -> dict[str, Any]:
        if df is None or len(df) == 0:
            return {}
        return {str(k): value_to_json(v) for k, v in df.iloc[-1].items()}

    return {
        "benchmark": benchmark,
        "ccy": getattr(al, "currency", ccy),
        "rolling_window": rolling_window,
        "beta": _last_row(al.index_beta(rolling_window=rolling_window)),
        "correlation": _last_row(al.index_corr(rolling_window=rolling_window)),
        "tracking_difference_annualized": _last_row(
            al.tracking_difference_annualized(rolling_window=rolling_window)
        ),
        "tracking_error": _last_row(al.tracking_error(rolling_window=rolling_window)),
    }
```

Add to `register`:

```python
    mcp.tool(get_benchmark_metrics)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_tool_asset_list.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/asset_list.py tests/test_tool_asset_list.py
git commit -m "feat(asset_list): add get_benchmark_metrics tool"
```

---

## Task 7: Return metrics — get_asset_returns + get_rolling_returns (asset_list)

**Files:**
- Modify: `src/okama_mcp/tools/asset_list.py`
- Test: `tests/test_tool_asset_list.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tool_asset_list.py`:

```python
class TestAssetReturns:
    def _mock(self):
        idx = pd.period_range("2015-01", periods=3, freq="M")
        years = pd.period_range("2015", periods=2, freq="Y")
        mock = SimpleNamespace()
        mock.symbols = ["SPY.US", "GLD.US"]
        mock.currency = "USD"
        mock.get_cagr = MagicMock(return_value=pd.DataFrame(
            {"SPY.US": [0.10, 0.11, 0.12], "GLD.US": [0.04, 0.05, 0.06]}, index=idx))
        mock.get_cumulative_return = MagicMock(return_value=pd.DataFrame(
            {"SPY.US": [0.30, 0.33, 0.36], "GLD.US": [0.12, 0.15, 0.18]}, index=idx))
        mock.mean_return = pd.Series({"SPY.US": 0.11, "GLD.US": 0.05})
        mock.real_mean_return = pd.Series({"SPY.US": 0.08, "GLD.US": 0.02})
        mock.get_monthly_geometric_mean_return = MagicMock(
            return_value=pd.Series({"SPY.US": 0.009, "GLD.US": 0.004}))
        mock.annual_return_ts = pd.DataFrame(
            {"SPY.US": [0.12, 0.10], "GLD.US": [0.05, 0.06]}, index=years)
        return mock

    def test_scalar_metrics_use_last_row(self) -> None:
        mock = self._mock()
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock):
            out = al_tool.get_asset_returns(["SPY.US", "GLD.US"], ccy="USD")
        assert out["cagr"] == {"SPY.US": 0.12, "GLD.US": 0.06}
        assert out["cumulative_return"] == {"SPY.US": 0.36, "GLD.US": 0.18}
        assert out["mean_return"] == {"SPY.US": 0.11, "GLD.US": 0.05}
        assert out["real_mean_return"] == {"SPY.US": 0.08, "GLD.US": 0.02}
        assert out["monthly_geom_mean"] == {"SPY.US": 0.009, "GLD.US": 0.004}
        assert out["annual_returns"]["columns"] == ["SPY.US", "GLD.US"]


class TestRollingReturns:
    def test_returns_rolling_frames(self) -> None:
        idx = pd.period_range("2016-01", periods=2, freq="M")
        rc = pd.DataFrame({"SPY.US": [0.09, 0.10]}, index=idx)
        rcr = pd.DataFrame({"SPY.US": [0.20, 0.22]}, index=idx)
        mock = SimpleNamespace()
        mock.symbols = ["SPY.US"]
        mock.currency = "USD"
        mock.get_rolling_cagr = MagicMock(return_value=rc)
        mock.get_rolling_cumulative_return = MagicMock(return_value=rcr)
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=mock):
            out = al_tool.get_rolling_returns(["SPY.US"], ccy="USD", window_months=12)
        assert out["window_months"] == 12
        assert out["rolling_cagr"]["columns"] == ["SPY.US"]
        assert out["rolling_cumulative_return"]["columns"] == ["SPY.US"]
        mock.get_rolling_cagr.assert_called_once_with(window=12, real=False)
        mock.get_rolling_cumulative_return.assert_called_once_with(window=12, real=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_tool_asset_list.py::TestAssetReturns tests/test_tool_asset_list.py::TestRollingReturns -q`
Expected: FAIL (tools undefined).

- [ ] **Step 3: Implement**

In `src/okama_mcp/tools/asset_list.py`, add before `register`:

```python
@translates_okama_errors
def get_asset_returns(
    symbols: list[str],
    ccy: str = "USD",
    first_date: str | None = None,
    last_date: str | None = None,
    inflation: bool = True,
    portfolios: list[dict[str, Any]] | None = None,
    period: int | None = None,
    real: bool = False,
) -> dict[str, Any]:
    """Return metrics for each asset (and any nested ``portfolios``).

    Scalar metrics are the latest (since-inception) value: ``cagr`` and
    ``cumulative_return`` are the last row of okama's expanding series;
    ``mean_return``/``real_mean_return``/``monthly_geom_mean`` are annualized
    per-asset values. ``annual_returns`` is the per-calendar-year return table.
    ``real=True`` returns inflation-adjusted CAGR/cumulative return (needs
    ``inflation=True``); ``period`` limits CAGR to the last N years.
    """
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)

    def _last_row(df: Any) -> dict[str, Any]:
        if df is None or len(df) == 0:
            return {}
        return {str(k): value_to_json(v) for k, v in df.iloc[-1].items()}

    def _series(s: Any) -> dict[str, Any]:
        return {str(k): value_to_json(v) for k, v in s.items()}

    return {
        "ccy": getattr(al, "currency", ccy),
        "period": period,
        "real": real,
        "cagr": _last_row(al.get_cagr(period=period, real=real)),
        "cumulative_return": _last_row(al.get_cumulative_return(real=real)),
        "mean_return": _series(al.mean_return),
        "real_mean_return": _series(al.real_mean_return),
        "monthly_geom_mean": _series(al.get_monthly_geometric_mean_return()),
        "annual_returns": dataframe_to_json(al.annual_return_ts),
    }


@translates_okama_errors
def get_rolling_returns(
    symbols: list[str],
    ccy: str = "USD",
    window_months: int = 12,
    real: bool = False,
    first_date: str | None = None,
    last_date: str | None = None,
    portfolios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rolling CAGR and rolling cumulative return for each asset.

    ``window_months`` is the moving-window size (okama recommends >= 12).
    ``real=True`` computes inflation-adjusted values (needs ``inflation`` data).
    """
    if window_months < 1:
        raise OkamaMcpError("window_months must be a positive number of months")
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation=real, portfolios=portfolios)
    return {
        "ccy": getattr(al, "currency", ccy),
        "window_months": window_months,
        "real": real,
        "rolling_cagr": dataframe_to_json(al.get_rolling_cagr(window=window_months, real=real)),
        "rolling_cumulative_return": dataframe_to_json(
            al.get_rolling_cumulative_return(window=window_months, real=real)
        ),
    }
```

Add to `register`:

```python
    mcp.tool(get_asset_returns)
    mcp.tool(get_rolling_returns)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_tool_asset_list.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/asset_list.py tests/test_tool_asset_list.py
git commit -m "feat(asset_list): add get_asset_returns and get_rolling_returns tools"
```

---

## Task 8: Plots — nesting-safe titles + plot_transition_map + plot_assets portfolios

**Files:**
- Modify: `src/okama_mcp/tools/plots.py`
- Test: `tests/test_tool_plots.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tool_plots.py`:

```python
def _make_ef_mock_for_tm() -> SimpleNamespace:
    ef = SimpleNamespace()
    ef.symbols = ["SPY.US", "GLD.US", "BND.US"]
    ef.currency = "USD"
    ef.ef_points = pd.DataFrame(
        {
            "Risk": [0.05, 0.08, 0.12, 0.18],
            "Mean return": [0.04, 0.07, 0.09, 0.11],
            "CAGR": [0.038, 0.067, 0.085, 0.105],
            "SPY.US": [0.10, 0.30, 0.60, 1.00],
            "GLD.US": [0.20, 0.30, 0.30, 0.00],
            "BND.US": [0.70, 0.40, 0.10, 0.00],
        }
    )
    return ef


VALID_FRONTIER_SPEC: dict = {
    "assets": ["SPY.US", "GLD.US", "BND.US"],
    "ccy": "USD",
    "n_points": 4,
}


class TestPlotTransitionMap:
    def test_returns_png_image(self) -> None:
        ef = _make_ef_mock_for_tm()
        with patch("okama_mcp.tools.frontier.ok.EfficientFrontier", return_value=ef), \
             patch("okama_mcp.tools.frontier.ok.Rebalance", return_value="REB"):
            out = plots_tool.plot_transition_map(VALID_FRONTIER_SPEC)
        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)

    def test_invalid_x_axe_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_transition_map(VALID_FRONTIER_SPEC, x_axe="time")
```

Note: `x_axe` is validated before building the frontier, so `test_invalid_x_axe_rejected` needs no okama mock.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_tool_plots.py::TestPlotTransitionMap -q`
Expected: FAIL (`plot_transition_map` undefined).

- [ ] **Step 3: Implement**

In `src/okama_mcp/tools/plots.py`, add a helper near the top (after `_plot_index_values`) and a module constant:

```python
_TM_NON_WEIGHT_COLS = {"Risk", "Mean return", "CAGR", "Weights", "iterations", "init_guess"}


def _join_symbols(obj: Any, spec: Any) -> str:
    """Comma-joined resolved symbols for chart titles (nesting-safe).

    Prefer the built object's ``.symbols`` (resolved, incl. nested-portfolio
    ``.PF`` labels); fall back to the spec's string tickers only.
    """
    syms = getattr(obj, "symbols", None)
    items = list(syms) if syms is not None else [a for a in spec.assets if isinstance(a, str)]
    return ", ".join(str(s) for s in items)
```

Replace the three nesting-unsafe titles:
- In `plot_wealth_index`: `ax.set_title(f"Wealth index — {_join_symbols(pf, spec)} ({spec.ccy})")`
- In `plot_drawdowns`: `ax.set_title(f"Drawdowns — {_join_symbols(pf, spec)} ({spec.ccy})")`
- In `plot_efficient_frontier`: `ax.set_title(f"Efficient frontier — {_join_symbols(ef, spec)} ({spec.ccy})")`

Add the new tool before `register`:

```python
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
```

Add `portfolios` to `plot_assets` (signature after `inflation`, before `width`): `portfolios: list[dict[str, Any]] | None = None`, and pass it through:

```python
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation, portfolios=portfolios)
```

Add to `register`:

```python
    mcp.tool(plot_transition_map)
```

Ensure `Any` is imported (it is: `from typing import Any`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_tool_plots.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/plots.py tests/test_tool_plots.py
git commit -m "feat(plots): add plot_transition_map; nesting-safe titles; portfolios on plot_assets"
```

---

## Task 9: Largest withdrawals size (monte_carlo)

**Files:**
- Modify: `src/okama_mcp/tools/monte_carlo.py`
- Test: `tests/test_tool_monte_carlo.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tool_monte_carlo.py`:

```python
class TestLargestWithdrawalsSize:
    def test_returns_withdrawal_result(self) -> None:
        pf = _make_pf_mock()
        pf.dcf.find_the_largest_withdrawals_size = MagicMock(
            return_value=SimpleNamespace(
                success=True,
                withdrawal_abs=-12345.0,
                withdrawal_rel=-0.04,
                error_rel=0.02,
                solutions=pd.DataFrame({"withdrawal_abs": [-1, -2, -3]}),
            )
        )
        ind_mock = MagicMock(name="IndexationStrategy_instance")
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=ind_mock),
        ):
            out = mc_tool.find_the_largest_withdrawals_size(
                portfolio=VALID_PF_SPEC,
                mc=VALID_MC_SPEC,
                cashflow=VALID_INDEXATION_CASHFLOW,
                goal="survival_period",
                target_survival_period=25,
                percentile=20,
            )
        assert out["goal"] == "survival_period"
        assert out["success"] is True
        assert out["withdrawal_abs"] == -12345.0
        assert out["withdrawal_rel"] == -0.04
        assert out["error_rel"] == 0.02
        assert out["n_evaluations"] == 3
        pf.dcf.set_mc_parameters.assert_called_once()

    def test_invalid_goal_rejected(self) -> None:
        with pytest.raises(OkamaMcpError):
            mc_tool.find_the_largest_withdrawals_size(
                portfolio=VALID_PF_SPEC,
                mc=VALID_MC_SPEC,
                cashflow=VALID_INDEXATION_CASHFLOW,
                goal="not_a_goal",
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_tool_monte_carlo.py::TestLargestWithdrawalsSize -q`
Expected: FAIL (`find_the_largest_withdrawals_size` undefined).

- [ ] **Step 3: Implement**

In `src/okama_mcp/tools/monte_carlo.py`, add a module constant near the top (after imports) and the tool before `register`:

```python
_WITHDRAWAL_GOALS = ("maintain_balance_pv", "maintain_balance_fv", "survival_period")
```

```python
@translates_okama_errors
def find_the_largest_withdrawals_size(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    cashflow: dict[str, Any],
    goal: str,
    withdrawals_range: tuple[float, float] = (0.0, 1.0),
    target_survival_period: int = 25,
    percentile: int = 20,
    threshold: float = 0.0,
    tolerance_rel: float = 0.1,
    iter_max: int = 20,
) -> dict[str, Any]:
    """Largest sustainable withdrawal size for a Monte Carlo cash-flow plan.

    ``goal`` is one of: ``maintain_balance_pv`` (keep real purchasing power),
    ``maintain_balance_fv`` (keep nominal value), or ``survival_period`` (last at
    least ``target_survival_period`` years). The ``cashflow`` strategy provides
    the base withdrawal that gets scaled; ``percentile`` is the Monte Carlo
    confidence percentile evaluated (e.g. 20 = pessimistic). Returns the found
    withdrawal in absolute and relative terms plus the solver's relative error.
    """
    if goal not in _WITHDRAWAL_GOALS:
        raise OkamaMcpError(f"goal must be one of {_WITHDRAWAL_GOALS}, got {goal!r}")
    pf, mc_spec = _prepare_dcf(portfolio, mc, cashflow)
    result = pf.dcf.find_the_largest_withdrawals_size(
        goal=goal,
        withdrawals_range=tuple(withdrawals_range),
        target_survival_period=target_survival_period,
        percentile=percentile,
        threshold=threshold,
        tolerance_rel=tolerance_rel,
        iter_max=iter_max,
    )
    solutions = getattr(result, "solutions", None)
    return {
        "goal": goal,
        "success": bool(getattr(result, "success", False)),
        "withdrawal_abs": value_to_json(float(result.withdrawal_abs)),
        "withdrawal_rel": value_to_json(float(result.withdrawal_rel)),
        "error_rel": value_to_json(float(result.error_rel)),
        "n_evaluations": int(len(solutions)) if solutions is not None else None,
        "mc_spec": mc_spec.model_dump(),
        "cashflow_spec": _validate_cashflow(cashflow).model_dump(),
    }
```

Add to `register`:

```python
    mcp.tool(find_the_largest_withdrawals_size)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_tool_monte_carlo.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/monte_carlo.py tests/test_tool_monte_carlo.py
git commit -m "feat(monte_carlo): add find_the_largest_withdrawals_size tool"
```

---

## Task 10: Full suite, lint, docs sync

**Files:**
- Modify: `README.md`
- Modify: `deploy/nginx/index.html`
- Possibly: `tests/test_server_bootstrap.py` (if it asserts a tool count)

- [ ] **Step 1: Run the full test suite**

Run: `poetry run pytest -q`
Expected: PASS. If `tests/test_server_bootstrap.py` asserts the number of registered tools, update the expected count to the new total (27 + 6 = 33) and re-run.

- [ ] **Step 2: Lint**

Run: `poetry run ruff check .`
Expected: no issues. Fix every reported item; only silence with a targeted `# noqa: <CODE>` + rationale if truly unavoidable (per AGENTS.md).

- [ ] **Step 3: Update README tool catalogue**

In `README.md`, add the six new tools to the tool catalogue/sections and a short note that portfolios can be nested as components inside `compare_assets`/efficient frontier/portfolio specs. New tools:
- `get_most_diversified_portfolio` (EfficientFrontier MDP)
- `get_benchmark_metrics` (beta / correlation / tracking difference / tracking error vs a benchmark)
- `plot_transition_map` (efficient-frontier transition map)
- `find_the_largest_withdrawals_size` (max sustainable withdrawal, Monte Carlo)
- `get_asset_returns` (CAGR / cumulative / mean / real mean / monthly geom mean / annual returns)
- `get_rolling_returns` (rolling CAGR & rolling cumulative return)

Also note Sharpe/Sortino now appear in `analyze_portfolio` and `compare_assets`.

- [ ] **Step 4: Sync the landing page**

Per AGENTS.md: the landing `deploy/nginx/index.html` is a teaser, not a full mirror. Update only what would otherwise contradict the README — e.g. a tool-count figure or feature highlights (mention benchmark metrics / transition map / retirement withdrawal sizing if the landing lists highlights). Do NOT mirror the full catalogue. (Deploy to `secondvds` and the live byte-diff verification are a separate release step — not part of this commit.)

- [ ] **Step 5: Commit**

```bash
git add README.md deploy/nginx/index.html tests/test_server_bootstrap.py
git commit -m "docs: document new okama tools + nested portfolios; sync landing"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** Task 1 = recursive specs; Task 2 = Portfolio/EF nesting; Task 3 = AssetList nesting + 3 tools; Task 4 = Sharpe/Sortino (item 1); Task 5 = MDP (item 2); Task 6 = benchmark (item 3); Task 7 = return metrics; Task 8 = transition map (item 4) + nesting-safe titles + plot_assets nesting; Task 9 = withdrawals (item 5); Task 10 = docs/lint/suite. All spec sections covered.
- **Tool count:** +6 (`get_most_diversified_portfolio`, `get_benchmark_metrics`, `get_asset_returns`, `get_rolling_returns`, `plot_transition_map`, `find_the_largest_withdrawals_size`) → 33.
- **Import direction:** `frontier`/`asset_list`/`plots` import from `portfolio`; `portfolio` imports none of them — no cycle.
- **Label safety:** `_weights_dict` (portfolio, fixed in Task 2) and chart titles (Task 8) use the built object's `.symbols`, never `spec.assets` (which may hold an unhashable nested model under nesting). Existing mocks set `pf.symbols`, so old tests stay green.
- **Naming consistency:** output keys verified against tests: `sharpe_ratio`, `sortino_ratio`, `weights`, `cagr`, `risk`, `diversification_ratio`, `beta`, `correlation`, `tracking_difference_annualized`, `tracking_error`, `cumulative_return`, `mean_return`, `real_mean_return`, `monthly_geom_mean`, `annual_returns`, `rolling_cagr`, `rolling_cumulative_return`, `withdrawal_abs`, `withdrawal_rel`, `error_rel`, `n_evaluations`.
