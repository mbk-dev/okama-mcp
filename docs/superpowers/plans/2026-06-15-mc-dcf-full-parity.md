# MC / DCF / distribution full-parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose all `okama.MonteCarlo` + `okama.PortfolioDCF` methods and custom Monte-Carlo distribution parameters as MCP tools (12 new tools, 33 → 45), keeping all 5 CashFlow strategies available.

**Architecture:** Thin stateless wrappers over okama, same as existing tools. New modules `tools/mc_diagnostics.py` (distribution diagnostics, no cashflow) and `tools/dcf.py` (historical/MC DCF, with cashflow) reuse shared builders from `tools/monte_carlo.py`. Two new plots are *replicated* on owned matplotlib Axes (not direct okama plot calls) for thread-safety, same rationale as `plot_transition_map`.

**Tech Stack:** Python 3.11, pydantic v2, okama ≥2.2.0, fastmcp, matplotlib (OO API via `okama_mcp.rendering`), scipy (for Q-Q / pdf overlay), pytest.

---

## File structure

- `src/okama_mcp/schemas.py` — modify: add `MCSpec.distribution_parameters` + validator; add `TimeSeriesCashflow.time_series_discounted_values`.
- `src/okama_mcp/tools/monte_carlo.py` — modify: add `_apply_mc_parameters`, `_prepare_mc`, `_prepare_cashflow`; thread `distribution_parameters` + `discount_rate` through `_prepare_dcf`.
- `src/okama_mcp/tools/mc_diagnostics.py` — create: 4 diagnostics tools + `register`.
- `src/okama_mcp/tools/dcf.py` — create: 6 DCF tools + `register`.
- `src/okama_mcp/tools/plots.py` — modify: add `plot_qq`, `plot_hist_fit`, register them.
- `src/okama_mcp/tools/__init__.py` — modify: import + register the two new modules.
- `pyproject.toml` + `requirements.txt` — modify: declare `scipy` explicitly.
- `tests/test_schemas.py`, `tests/test_tool_monte_carlo.py` — modify.
- `tests/test_tool_mc_diagnostics.py`, `tests/test_tool_dcf.py` — create.
- `README.md` — modify: tool catalog.

---

## Task 1: MCSpec.distribution_parameters

**Files:**
- Modify: `src/okama_mcp/schemas.py` (near line 31 `Distribution`, and `MCSpec` ~114-135)
- Test: `tests/test_schemas.py` (class `TestMCSpec`)

- [ ] **Step 1: Write failing tests**

In `tests/test_schemas.py`, inside `class TestMCSpec`, add:

```python
    def test_distribution_parameters_default_none(self) -> None:
        assert MCSpec().distribution_parameters is None

    def test_distribution_parameters_norm_length(self) -> None:
        assert MCSpec(distribution="norm", distribution_parameters=[0.01, 0.04]).distribution_parameters == [0.01, 0.04]
        with pytest.raises(ValidationError):
            MCSpec(distribution="norm", distribution_parameters=[0.01, 0.04, 0.1])

    def test_distribution_parameters_t_length(self) -> None:
        assert MCSpec(distribution="t", distribution_parameters=[3, None, None]).distribution_parameters == [3, None, None]
        with pytest.raises(ValidationError):
            MCSpec(distribution="t", distribution_parameters=[3, None])

    def test_distribution_parameters_lognorm_length(self) -> None:
        with pytest.raises(ValidationError):
            MCSpec(distribution="lognorm", distribution_parameters=[0.1, 0.2])
```

- [ ] **Step 2: Run tests, verify FAIL**

Run: `poetry run pytest tests/test_schemas.py::TestMCSpec -q`
Expected: FAIL — `distribution_parameters` not a field / no length validation.

- [ ] **Step 3: Implement**

In `src/okama_mcp/schemas.py`, after the `Distribution = Literal[...]` line (~31) add:

```python
_DIST_PARAM_LENGTHS: dict[str, int] = {"norm": 2, "lognorm": 3, "t": 3}
```

In `MCSpec`, add the field after `random_seed` (~126):

```python
    distribution_parameters: list[float | None] | None = Field(
        default=None,
        description=(
            "Optional explicit distribution parameters; any None element is fitted "
            "from history via MLE. Lengths by distribution: norm=[mu, sigma]; "
            "lognorm=[shape, loc, scale]; t=[df, loc, scale]."
        ),
    )
```

And add a second validator below `_validate_percentiles`:

```python
    @model_validator(mode="after")
    def _validate_distribution_parameters(self) -> MCSpec:
        if self.distribution_parameters is not None:
            expected = _DIST_PARAM_LENGTHS[self.distribution]
            if len(self.distribution_parameters) != expected:
                raise ValueError(
                    f"distribution_parameters for '{self.distribution}' must have "
                    f"{expected} elements, got {len(self.distribution_parameters)}"
                )
        return self
```

- [ ] **Step 4: Run tests, verify PASS**

Run: `poetry run pytest tests/test_schemas.py::TestMCSpec -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add MCSpec.distribution_parameters with per-distribution length validation"
```

---

## Task 2: TimeSeriesCashflow.time_series_discounted_values

**Files:**
- Modify: `src/okama_mcp/schemas.py` (`TimeSeriesCashflow` ~173-179)
- Modify: `src/okama_mcp/tools/monte_carlo.py` (`_build_cashflow_strategy` TimeSeries branch ~70-74)
- Test: `tests/test_schemas.py`, `tests/test_tool_monte_carlo.py`

- [ ] **Step 1: Write failing tests**

In `tests/test_schemas.py` add a class:

```python
class TestTimeSeriesDiscounted:
    def test_default_false(self) -> None:
        spec = TimeSeriesCashflow(initial_investment=100.0, events={"2030-01": -50.0})
        assert spec.time_series_discounted_values is False

    def test_can_set_true(self) -> None:
        spec = TimeSeriesCashflow(
            initial_investment=100.0, events={"2030-01": -50.0}, time_series_discounted_values=True
        )
        assert spec.time_series_discounted_values is True
```

In `tests/test_tool_monte_carlo.py`, inside `class TestTimeSeriesCashflow`, add:

```python
    def test_passes_discounted_values_flag(self) -> None:
        pf = _make_pf_mock()
        strat = MagicMock(name="TimeSeriesStrategy_instance")
        cf_spec = {
            "type": "time_series",
            "initial_investment": 100_000.0,
            "events": {"2030-01": -50_000},
            "time_series_discounted_values": True,
        }
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.TimeSeriesStrategy", return_value=strat),
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, VALID_MC_SPEC, cf_spec)
        assert strat.time_series_discounted_values is True
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_schemas.py::TestTimeSeriesDiscounted tests/test_tool_monte_carlo.py::TestTimeSeriesCashflow -q`
Expected: FAIL — field unknown / attribute not set.

- [ ] **Step 3: Implement**

In `schemas.py` `TimeSeriesCashflow`, add after `events`:

```python
    time_series_discounted_values: bool = Field(
        default=False,
        description="If true, event values are interpreted as present values (PV) instead of nominal.",
    )
```

In `monte_carlo.py` `_build_cashflow_strategy`, TimeSeries branch:

```python
    if isinstance(cashflow, TimeSeriesCashflow):
        strat = ok.TimeSeriesStrategy(pf)
        strat.initial_investment = cashflow.initial_investment
        strat.time_series_dic = dict(cashflow.events)
        strat.time_series_discounted_values = cashflow.time_series_discounted_values
        return strat
```

- [ ] **Step 4: Run, verify PASS**

Run: `poetry run pytest tests/test_schemas.py::TestTimeSeriesDiscounted tests/test_tool_monte_carlo.py::TestTimeSeriesCashflow -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/schemas.py src/okama_mcp/tools/monte_carlo.py tests/test_schemas.py tests/test_tool_monte_carlo.py
git commit -m "feat(cashflow): expose time_series_discounted_values on TimeSeriesCashflow"
```

---

## Task 3: Shared builders — distribution_parameters + discount_rate + _prepare_mc/_prepare_cashflow

**Files:**
- Modify: `src/okama_mcp/tools/monte_carlo.py` (`_prepare_dcf` ~161-177; add helpers)
- Test: `tests/test_tool_monte_carlo.py`

- [ ] **Step 1: Update existing assertion + write new tests**

In `tests/test_tool_monte_carlo.py`, the existing test asserts `set_mc_parameters` is called without `distribution_parameters`. Change that assertion (in `TestIndexationCashflow`, ~130-132) to:

```python
        pf.dcf.set_mc_parameters.assert_called_once_with(
            distribution="norm", distribution_parameters=None, period=25, mc_number=4, seed=None
        )
```

Add a new test class:

```python
class TestPrepareHelpers:
    def test_distribution_parameters_passed_as_tuple(self) -> None:
        pf = _make_pf_mock()
        mc_spec = dict(VALID_MC_SPEC, distribution="t", distribution_parameters=[3, None, None])
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            mc_tool.monte_carlo_forecast(VALID_PF_SPEC, mc_spec, VALID_INDEXATION_CASHFLOW)
        kwargs = pf.dcf.set_mc_parameters.call_args.kwargs
        assert kwargs["distribution_parameters"] == (3, None, None)

    def test_prepare_cashflow_no_mc_call(self) -> None:
        pf = _make_pf_mock()
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
            patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
        ):
            built_pf, spec = mc_tool._prepare_cashflow(VALID_PF_SPEC, VALID_INDEXATION_CASHFLOW, discount_rate=0.07)
        pf.dcf.set_mc_parameters.assert_not_called()
        assert pf.dcf.discount_rate == 0.07

    def test_prepare_mc_sets_params_no_cashflow(self) -> None:
        pf = _make_pf_mock()
        with (
            patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
            patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
        ):
            built_pf, spec = mc_tool._prepare_mc(VALID_PF_SPEC, VALID_MC_SPEC)
        pf.dcf.set_mc_parameters.assert_called_once()
        assert built_pf is pf
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_monte_carlo.py::TestPrepareHelpers tests/test_tool_monte_carlo.py::TestIndexationCashflow -q`
Expected: FAIL — `_prepare_cashflow`/`_prepare_mc` missing; `distribution_parameters` not passed.

- [ ] **Step 3: Implement**

In `monte_carlo.py`, replace `_prepare_dcf` (and add helpers) with:

```python
def _apply_mc_parameters(pf: Any, mc_spec: MCSpec) -> None:
    """Push MCSpec onto the portfolio's DCF Monte Carlo config."""
    pf.dcf.set_mc_parameters(
        distribution=mc_spec.distribution,
        distribution_parameters=(
            tuple(mc_spec.distribution_parameters)
            if mc_spec.distribution_parameters is not None
            else None
        ),
        period=mc_spec.period_years,
        mc_number=mc_spec.scenarios,
        seed=mc_spec.random_seed,
    )


def _prepare_dcf(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    cashflow: dict[str, Any],
    discount_rate: float | None = None,
) -> tuple[Any, MCSpec]:
    """Validate specs and return (Portfolio configured for MC + cashflow, MCSpec)."""
    mc_spec = _validate_mc(mc)
    cashflow_spec = _validate_cashflow(cashflow)
    _, pf = _get_portfolio(portfolio)
    _apply_mc_parameters(pf, mc_spec)
    if discount_rate is not None:
        pf.dcf.discount_rate = discount_rate
    strategy = _build_cashflow_strategy(pf, cashflow_spec)
    pf.dcf.cashflow_parameters = strategy
    return pf, mc_spec


def _prepare_mc(portfolio: dict[str, Any], mc: dict[str, Any]) -> tuple[Any, MCSpec]:
    """Build the portfolio and configure MC parameters WITHOUT a cashflow.

    For distribution-diagnostics tools that only read ``pf.dcf.mc``.
    """
    mc_spec = _validate_mc(mc)
    _, pf = _get_portfolio(portfolio)
    _apply_mc_parameters(pf, mc_spec)
    return pf, mc_spec


def _prepare_cashflow(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    discount_rate: float | None = None,
) -> tuple[Any, Any]:
    """Build the portfolio + cashflow strategy WITHOUT MC parameters.

    For historical DCF tools (wealth index, cash flow, survival) that don't simulate.
    """
    cashflow_spec = _validate_cashflow(cashflow)
    _, pf = _get_portfolio(portfolio)
    if discount_rate is not None:
        pf.dcf.discount_rate = discount_rate
    strategy = _build_cashflow_strategy(pf, cashflow_spec)
    pf.dcf.cashflow_parameters = strategy
    return pf, cashflow_spec
```

- [ ] **Step 4: Run, verify PASS (whole MC test module stays green)**

Run: `poetry run pytest tests/test_tool_monte_carlo.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/monte_carlo.py tests/test_tool_monte_carlo.py
git commit -m "refactor(dcf): thread distribution_parameters/discount_rate; add _prepare_mc/_prepare_cashflow"
```

---

## Task 4: scipy as an explicit dependency

**Files:**
- Modify: `pyproject.toml`, `requirements.txt`

- [ ] **Step 1: Add scipy**

Run: `poetry add scipy`
(okama already pulls scipy transitively; this declares it for the direct imports in Task 13–14.)

- [ ] **Step 2: Mirror into requirements.txt**

Add a line `scipy` (matching the resolved version range) to `requirements.txt`, consistent with how other deps are listed there.

- [ ] **Step 3: Verify import**

Run: `poetry run python -c "import scipy.stats; print(scipy.__version__)"`
Expected: prints a version, no error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "build: declare scipy as a direct dependency"
```

> Note: do NOT commit `poetry.lock` (project rule).

---

## Task 5: tools/mc_diagnostics.py — get_distribution_fit

**Files:**
- Create: `src/okama_mcp/tools/mc_diagnostics.py`
- Test: `tests/test_tool_mc_diagnostics.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_tool_mc_diagnostics.py`:

```python
"""Tests for tools/mc_diagnostics.py (offline, mocked okama)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from okama_mcp.tools import mc_diagnostics as diag
from okama_mcp.tools import portfolio as pf_tool


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    pf_tool.clear_cache()


VALID_PF_SPEC: dict = {
    "assets": ["GLD.US", "VNQ.US"],
    "weights": [0.3, 0.7],
    "ccy": "USD",
    "rebalancing_strategy": {"period": "year"},
    "inflation": True,
}
VALID_MC_SPEC: dict = {"distribution": "t", "period_years": 10, "scenarios": 100}


def _make_pf_mock_with_mc() -> SimpleNamespace:
    pf = SimpleNamespace()
    pf.symbol = "pf.PF"
    pf.symbols = ["GLD.US", "VNQ.US"]
    dcf = SimpleNamespace()
    dcf.set_mc_parameters = MagicMock()
    mc = SimpleNamespace()
    mc.get_parameters_for_distribution = MagicMock(return_value=(5.0, 0.01, 0.04))
    mc.jarque_bera = {"statistic": 58.3, "p-value": 2e-13}
    mc.kstest = {"statistic": 0.05, "p-value": 0.68}
    mc.kstest_for_all_distributions = pd.DataFrame(
        {"statistic": [0.09, 0.05, 0.04], "p-value": [0.04, 0.68, 0.8]},
        index=["norm", "lognorm", "t"],
    )
    mc.backtesting_error = MagicMock(
        return_value={"delta_arithmetic_mean": 0.001, "delta_var": -0.002, "delta_cvar": 0.003}
    )
    dcf.mc = mc
    pf.dcf = dcf
    return pf


def test_get_distribution_fit_shape() -> None:
    pf = _make_pf_mock_with_mc()
    with (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
    ):
        out = diag.get_distribution_fit(VALID_PF_SPEC, VALID_MC_SPEC)
    assert out["distribution"] == "t"
    assert out["parameters"] == [5.0, 0.01, 0.04]
    assert set(out["jarque_bera"]) == {"statistic", "p-value"}
    assert set(out["kstest"]) == {"statistic", "p-value"}
    assert "kstest_all_distributions" in out
    assert set(out["backtesting_error"]) == {"delta_arithmetic_mean", "delta_var", "delta_cvar"}
    pf.dcf.set_mc_parameters.assert_called_once()
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_mc_diagnostics.py -q`
Expected: FAIL — module `mc_diagnostics` does not exist.

- [ ] **Step 3: Implement**

Create `src/okama_mcp/tools/mc_diagnostics.py`:

```python
"""Monte Carlo distribution-fit diagnostics.

These tools read the portfolio's historical returns and the fitted distribution
(``pf.dcf.mc``); they do NOT require a cashflow strategy. Each accepts a full
PortfolioSpec + MCSpec — distribution and (optional) distribution_parameters drive
the goodness-of-fit numbers.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from okama_mcp.errors import translates_okama_errors
from okama_mcp.serialization import dataframe_to_json, series_to_json, value_to_json
from okama_mcp.tools.monte_carlo import _prepare_mc


@translates_okama_errors
def get_distribution_fit(portfolio: dict[str, Any], mc: dict[str, Any]) -> dict[str, Any]:
    """Goodness-of-fit diagnostics for the portfolio's return distribution.

    Parameters
    ----------
    portfolio : dict
        :class:`PortfolioSpec`.
    mc : dict
        :class:`MCSpec` — ``distribution`` (and optional ``distribution_parameters``)
        select the theoretical distribution being tested.

    Returns
    -------
    dict with the resolved (fitted) ``parameters`` tuple, ``jarque_bera`` (normality),
    ``kstest`` (Kolmogorov-Smirnov for the chosen distribution),
    ``kstest_all_distributions`` (KS for norm/lognorm/t), and ``backtesting_error``
    (theoretical-vs-empirical mean/VaR/CVaR deltas).
    """
    pf, mc_spec = _prepare_mc(portfolio, mc)
    m = pf.dcf.mc
    return {
        "mc_spec": mc_spec.model_dump(),
        "distribution": mc_spec.distribution,
        "parameters": [value_to_json(float(p)) for p in m.get_parameters_for_distribution()],
        "jarque_bera": {k: value_to_json(v) for k, v in m.jarque_bera.items()},
        "kstest": {k: value_to_json(v) for k, v in m.kstest.items()},
        "kstest_all_distributions": dataframe_to_json(m.kstest_for_all_distributions, full=True),
        "backtesting_error": {k: value_to_json(v) for k, v in m.backtesting_error().items()},
    }


def register(mcp: FastMCP) -> None:
    """Register MC distribution-diagnostics tools."""
    mcp.tool(get_distribution_fit)
```

(Note: `series_to_json` import is used by Task 6; leave it imported now to avoid churn — ruff F401 will flag it until Task 6, so add Task 6 in the same session OR temporarily drop the import. Cleanest: add the import in Task 6. For Task 5 alone, import only `dataframe_to_json, value_to_json`.)

For Task 5 standalone, the import line is:

```python
from okama_mcp.serialization import dataframe_to_json, value_to_json
```

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_mc_diagnostics.py -q && poetry run ruff check src/okama_mcp/tools/mc_diagnostics.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/mc_diagnostics.py tests/test_tool_mc_diagnostics.py
git commit -m "feat(mc): add get_distribution_fit diagnostics tool"
```

---

## Task 6: get_return_moments

**Files:**
- Modify: `src/okama_mcp/tools/mc_diagnostics.py`
- Test: `tests/test_tool_mc_diagnostics.py`

- [ ] **Step 1: Write failing test**

Append to `_make_pf_mock_with_mc` the moment attributes (edit the fixture):

```python
    mc.skewness = pd.Series([0.1, 0.2, 0.3], index=pd.period_range("2020-01", periods=3, freq="M"))
    mc.kurtosis = pd.Series([1.1, 1.2, 1.3], index=pd.period_range("2020-01", periods=3, freq="M"))
    mc.skewness_rolling = MagicMock(return_value=pd.Series([0.4, 0.5]))
    mc.kurtosis_rolling = MagicMock(return_value=pd.Series([2.1, 2.2]))
```

Add test:

```python
def test_get_return_moments_expanding_and_rolling() -> None:
    pf = _make_pf_mock_with_mc()
    with (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
    ):
        out = diag.get_return_moments(VALID_PF_SPEC, VALID_MC_SPEC)
        out_roll = diag.get_return_moments(VALID_PF_SPEC, VALID_MC_SPEC, rolling_window=24)
    assert "skewness" in out and "kurtosis" in out
    assert out["rolling_window"] is None
    pf.dcf.mc.skewness_rolling.assert_called_once_with(window=24)
    assert out_roll["rolling_window"] == 24
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_mc_diagnostics.py::test_get_return_moments_expanding_and_rolling -q`
Expected: FAIL — `get_return_moments` missing.

- [ ] **Step 3: Implement**

In `mc_diagnostics.py`, change the serialization import to include `series_to_json`:

```python
from okama_mcp.serialization import dataframe_to_json, series_to_json, value_to_json
```

Add the tool before `register`:

```python
@translates_okama_errors
def get_return_moments(
    portfolio: dict[str, Any], mc: dict[str, Any], rolling_window: int | None = None
) -> dict[str, Any]:
    """Skewness and kurtosis time series for the portfolio's returns.

    With ``rolling_window=None`` (default) returns the expanding-window series;
    pass a window in months (>=12) for the rolling version. Long series are
    truncated to head/tail/summary.
    """
    pf, mc_spec = _prepare_mc(portfolio, mc)
    m = pf.dcf.mc
    if rolling_window is None:
        skew, kurt = m.skewness, m.kurtosis
    else:
        skew = m.skewness_rolling(window=rolling_window)
        kurt = m.kurtosis_rolling(window=rolling_window)
    return {
        "mc_spec": mc_spec.model_dump(),
        "rolling_window": rolling_window,
        "skewness": series_to_json(skew),
        "kurtosis": series_to_json(kurt),
    }
```

Register it:

```python
    mcp.tool(get_return_moments)
```

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_mc_diagnostics.py -q && poetry run ruff check src/okama_mcp/tools/mc_diagnostics.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/mc_diagnostics.py tests/test_tool_mc_diagnostics.py
git commit -m "feat(mc): add get_return_moments (skewness/kurtosis, expanding+rolling)"
```

---

## Task 7: optimize_students_df

**Files:**
- Modify: `src/okama_mcp/tools/mc_diagnostics.py`
- Test: `tests/test_tool_mc_diagnostics.py`

- [ ] **Step 1: Write failing test**

Add to the fixture: `mc.optimize_df_for_students = MagicMock(return_value=4.7)`

Add test:

```python
def test_optimize_students_df() -> None:
    pf = _make_pf_mock_with_mc()
    with (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
    ):
        out = diag.optimize_students_df(VALID_PF_SPEC, VALID_MC_SPEC, var_level=5)
    assert out["var_level"] == 5
    assert out["degrees_of_freedom"] == 4.7
    pf.dcf.mc.optimize_df_for_students.assert_called_once_with(var_level=5)
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_mc_diagnostics.py::test_optimize_students_df -q`
Expected: FAIL — tool missing.

- [ ] **Step 3: Implement**

Add before `register`:

```python
@translates_okama_errors
def optimize_students_df(
    portfolio: dict[str, Any], mc: dict[str, Any], var_level: int = 5
) -> dict[str, Any]:
    """Degrees of freedom for a Student-t that best matches empirical VaR/CVaR.

    ``var_level`` is the tail percent (1..99, default 5). Useful for choosing the
    ``df`` to pass back in ``MCSpec.distribution_parameters`` for a t-distribution.
    """
    pf, mc_spec = _prepare_mc(portfolio, mc)
    df = pf.dcf.mc.optimize_df_for_students(var_level=var_level)
    return {
        "mc_spec": mc_spec.model_dump(),
        "var_level": var_level,
        "degrees_of_freedom": value_to_json(float(df)),
    }
```

Register: `mcp.tool(optimize_students_df)`

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_mc_diagnostics.py -q && poetry run ruff check src/okama_mcp/tools/mc_diagnostics.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/mc_diagnostics.py tests/test_tool_mc_diagnostics.py
git commit -m "feat(mc): add optimize_students_df tool"
```

---

## Task 8: get_cagr_distribution

**Files:**
- Modify: `src/okama_mcp/tools/mc_diagnostics.py`
- Test: `tests/test_tool_mc_diagnostics.py`

- [ ] **Step 1: Write failing test**

Add to fixture:

```python
    mc.percentile_distribution_cagr = MagicMock(return_value={10: -0.02, 50: 0.05, 90: 0.12})
    mc.percentile_inverse_cagr = MagicMock(return_value=8.0)
```

Add test:

```python
def test_get_cagr_distribution() -> None:
    pf = _make_pf_mock_with_mc()
    with (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
    ):
        out = diag.get_cagr_distribution(VALID_PF_SPEC, VALID_MC_SPEC, percentiles=[10, 50, 90], score=0.0)
    assert out["percentiles"] == {"10": -0.02, "50": 0.05, "90": 0.12}
    assert out["prob_below_score_pct"] == 8.0
    pf.dcf.mc.percentile_distribution_cagr.assert_called_once_with(percentiles=[10, 50, 90])
    pf.dcf.mc.percentile_inverse_cagr.assert_called_once_with(score=0.0)
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_mc_diagnostics.py::test_get_cagr_distribution -q`
Expected: FAIL — tool missing.

- [ ] **Step 3: Implement**

Add before `register`:

```python
@translates_okama_errors
def get_cagr_distribution(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    percentiles: list[int] | None = None,
    score: float = 0.0,
) -> dict[str, Any]:
    """Simulated CAGR distribution from the Monte Carlo paths.

    ``percentiles`` (default [10, 50, 90]) → the CAGR at each percentile.
    ``score`` (default 0.0) → ``prob_below_score_pct``: the share of simulated
    CAGRs at or below ``score`` (e.g. score=0 = probability of a negative result).
    """
    if percentiles is None:
        percentiles = [10, 50, 90]
    pf, mc_spec = _prepare_mc(portfolio, mc)
    m = pf.dcf.mc
    dist = m.percentile_distribution_cagr(percentiles=list(percentiles))
    rank = m.percentile_inverse_cagr(score=score)
    return {
        "mc_spec": mc_spec.model_dump(),
        "percentiles": {str(k): value_to_json(float(v)) for k, v in dist.items()},
        "score": value_to_json(float(score)),
        "prob_below_score_pct": value_to_json(float(rank)),
    }
```

Register: `mcp.tool(get_cagr_distribution)`

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_mc_diagnostics.py -q && poetry run ruff check src/okama_mcp/tools/mc_diagnostics.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/mc_diagnostics.py tests/test_tool_mc_diagnostics.py
git commit -m "feat(mc): add get_cagr_distribution tool"
```

---

## Task 9: tools/dcf.py — get_dcf_wealth_index + get_dcf_cash_flow_ts

**Files:**
- Create: `src/okama_mcp/tools/dcf.py`
- Test: `tests/test_tool_dcf.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tool_dcf.py`:

```python
"""Tests for tools/dcf.py (offline, mocked okama)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from okama_mcp.tools import dcf as dcf_tool
from okama_mcp.tools import portfolio as pf_tool


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    pf_tool.clear_cache()


VALID_PF_SPEC: dict = {
    "assets": ["GLD.US", "VNQ.US"],
    "weights": [0.3, 0.7],
    "ccy": "USD",
    "rebalancing_strategy": {"period": "year"},
    "inflation": True,
}
VALID_MC_SPEC: dict = {"distribution": "norm", "period_years": 10, "scenarios": 50, "percentiles": [5, 50, 95]}
VALID_CASHFLOW: dict = {
    "type": "indexation",
    "initial_investment": 100_000.0,
    "frequency": "year",
    "amount": -5_000.0,
    "indexation": "inflation",
}


def _idx(n: int) -> pd.PeriodIndex:
    return pd.period_range("2015-01", periods=n, freq="M")


def _make_pf_mock_dcf() -> SimpleNamespace:
    pf = SimpleNamespace()
    pf.symbol = "pf.PF"
    pf.symbols = ["GLD.US", "VNQ.US"]
    dcf = SimpleNamespace()
    dcf.set_mc_parameters = MagicMock()
    dcf.discount_rate = 0.04
    dcf.wealth_index = MagicMock(
        return_value=pd.DataFrame({"pf.PF": [100.0, 101.0, 102.0]}, index=_idx(3))
    )
    dcf.cash_flow_ts = MagicMock(return_value=pd.Series([-5.0, -5.0, -5.0], index=_idx(3), name="cf"))
    dcf.wealth_index_fv_with_assets = pd.DataFrame(
        {"pf.PF": [100.0, 101.0], "GLD.US": [50.0, 51.0]}, index=_idx(2)
    )
    dcf.survival_period_hist = MagicMock(return_value=12.5)
    dcf.survival_date_hist = MagicMock(return_value=pd.Timestamp("2027-07-31"))
    dcf.initial_investment_pv = 65_000.0
    dcf.initial_investment_fv = 100_000.0
    dcf.monte_carlo_cash_flow = MagicMock(
        return_value=pd.DataFrame({"s0": [-5.0, -5.1], "s1": [-5.0, -4.9]}, index=_idx(2))
    )
    pf.dcf = dcf
    return pf


def _patches(pf: SimpleNamespace):
    return (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
        patch("okama_mcp.tools.monte_carlo.ok.IndexationStrategy", return_value=MagicMock()),
    )


def test_get_dcf_wealth_index() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_dcf_wealth_index(VALID_PF_SPEC, VALID_CASHFLOW, discounting="fv", discount_rate=0.05)
    assert out["discounting"] == "fv"
    assert "wealth_index" in out
    pf.dcf.wealth_index.assert_called_once_with(discounting="fv", include_negative_values=False)
    assert pf.dcf.discount_rate == 0.05
    pf.dcf.set_mc_parameters.assert_not_called()


def test_get_dcf_cash_flow_ts() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_dcf_cash_flow_ts(VALID_PF_SPEC, VALID_CASHFLOW, discounting="pv")
    assert out["discounting"] == "pv"
    assert "cash_flow" in out
    pf.dcf.cash_flow_ts.assert_called_once_with(discounting="pv", remove_if_wealth_index_negative=True)
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_dcf.py -q`
Expected: FAIL — module `dcf` missing.

- [ ] **Step 3: Implement**

Create `src/okama_mcp/tools/dcf.py`:

```python
"""Discounted-cash-flow (DCF) tools over okama.PortfolioDCF.

Historical tools (wealth index, cash flow, survival, initial investment) take a
PortfolioSpec + CashflowSpec and never simulate. The Monte Carlo cash-flow tool
additionally takes an MCSpec and returns percentile bands (never the raw matrix).
``discount_rate`` is optional; when omitted okama's default is used.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from okama_mcp.errors import translates_okama_errors
from okama_mcp.serialization import to_json, value_to_json
from okama_mcp.tools.monte_carlo import (
    _mc_index_iso,
    _percentile_bands,
    _prepare_cashflow,
    _prepare_dcf,
    _validate_cashflow,
)


@translates_okama_errors
def get_dcf_wealth_index(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    discounting: str = "fv",
    include_negative_values: bool = False,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Historical wealth index of the portfolio with a cash-flow plan.

    ``discounting``: 'fv' (nominal) or 'pv' (discounted by ``discount_rate``).
    Returns the portfolio (+ accumulated inflation) wealth series, truncated.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow, discount_rate=discount_rate)
    wi = pf.dcf.wealth_index(discounting=discounting, include_negative_values=include_negative_values)
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "discounting": discounting,
        "wealth_index": to_json(wi),
    }


@translates_okama_errors
def get_dcf_cash_flow_ts(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    discounting: str = "fv",
    remove_if_wealth_index_negative: bool = True,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Historical cash-flow (contributions/withdrawals) time series.

    ``discounting``: 'fv' or 'pv'. ``remove_if_wealth_index_negative`` zeroes the
    cash flow after the portfolio is depleted. Series is truncated.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow, discount_rate=discount_rate)
    cf = pf.dcf.cash_flow_ts(
        discounting=discounting, remove_if_wealth_index_negative=remove_if_wealth_index_negative
    )
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "discounting": discounting,
        "cash_flow": to_json(cf),
    }


def register(mcp: FastMCP) -> None:
    """Register DCF tools."""
    mcp.tool(get_dcf_wealth_index)
    mcp.tool(get_dcf_cash_flow_ts)
```

(Imports `_mc_index_iso`, `_percentile_bands`, `_prepare_dcf`, `_validate_cashflow`, `value_to_json` are used by Tasks 11–13; if running Task 9 standalone, import only what's used: `to_json`, `_prepare_cashflow`. Add the rest in the tasks that use them to keep ruff clean.)

For Task 9 standalone the imports are:

```python
from okama_mcp.serialization import to_json
from okama_mcp.tools.monte_carlo import _prepare_cashflow
```

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_dcf.py -q && poetry run ruff check src/okama_mcp/tools/dcf.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/dcf.py tests/test_tool_dcf.py
git commit -m "feat(dcf): add get_dcf_wealth_index + get_dcf_cash_flow_ts"
```

---

## Task 10: get_dcf_wealth_with_assets

**Files:**
- Modify: `src/okama_mcp/tools/dcf.py`
- Test: `tests/test_tool_dcf.py`

- [ ] **Step 1: Write failing test**

```python
def test_get_dcf_wealth_with_assets() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_dcf_wealth_with_assets(VALID_PF_SPEC, VALID_CASHFLOW)
    assert "wealth_index" in out
    assert out["wealth_index"]["columns"] == ["pf.PF", "GLD.US"]
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_dcf.py::test_get_dcf_wealth_with_assets -q`
Expected: FAIL — tool missing.

- [ ] **Step 3: Implement**

Add before `register`:

```python
@translates_okama_errors
def get_dcf_wealth_with_assets(
    portfolio: dict[str, Any], cashflow: dict[str, Any]
) -> dict[str, Any]:
    """Historical wealth index (FV) for the portfolio AND each underlying asset.

    Adds the accumulated-inflation column when the portfolio has inflation. The
    DataFrame is truncated (head/tail/summary) for long histories.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow)
    df = pf.dcf.wealth_index_fv_with_assets
    return {"cashflow_spec": cashflow_spec.model_dump(), "wealth_index": to_json(df)}
```

Register: `mcp.tool(get_dcf_wealth_with_assets)`

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_dcf.py -q && poetry run ruff check src/okama_mcp/tools/dcf.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/dcf.py tests/test_tool_dcf.py
git commit -m "feat(dcf): add get_dcf_wealth_with_assets"
```

---

## Task 11: get_survival_period

**Files:**
- Modify: `src/okama_mcp/tools/dcf.py`
- Test: `tests/test_tool_dcf.py`

- [ ] **Step 1: Write failing test**

```python
def test_get_survival_period() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_survival_period(VALID_PF_SPEC, VALID_CASHFLOW, threshold=0.0, discount_rate=0.03)
    assert out["survival_period_years"] == 12.5
    assert out["survival_date"] == "2027-07-31"
    pf.dcf.survival_period_hist.assert_called_once_with(threshold=0.0)
    assert pf.dcf.discount_rate == 0.03
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_dcf.py::test_get_survival_period -q`
Expected: FAIL — tool missing.

- [ ] **Step 3: Implement**

Add the import `value_to_json` to the serialization import line:

```python
from okama_mcp.serialization import to_json, value_to_json
```

Add before `register`:

```python
@translates_okama_errors
def get_survival_period(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    threshold: float = 0.0,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Historical portfolio longevity under the cash-flow plan.

    ``threshold`` is the fraction of the initial investment at which the balance
    is considered depleted (relevant for percentage withdrawals). Returns the
    survival period in years and the depletion date.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow, discount_rate=discount_rate)
    period = pf.dcf.survival_period_hist(threshold=threshold)
    date = pf.dcf.survival_date_hist(threshold=threshold)
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "threshold": value_to_json(float(threshold)),
        "survival_period_years": value_to_json(float(period)),
        "survival_date": value_to_json(date),
    }
```

Register: `mcp.tool(get_survival_period)`

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_dcf.py -q && poetry run ruff check src/okama_mcp/tools/dcf.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/dcf.py tests/test_tool_dcf.py
git commit -m "feat(dcf): add get_survival_period (period + date)"
```

---

## Task 12: get_initial_investment_values

**Files:**
- Modify: `src/okama_mcp/tools/dcf.py`
- Test: `tests/test_tool_dcf.py`

- [ ] **Step 1: Write failing test**

```python
def test_get_initial_investment_values() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_initial_investment_values(VALID_PF_SPEC, VALID_CASHFLOW, discount_rate=0.10)
    assert out["pv"] == 65_000.0
    assert out["fv"] == 100_000.0
    assert out["discount_rate"] == 0.10
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_dcf.py::test_get_initial_investment_values -q`
Expected: FAIL — tool missing.

- [ ] **Step 3: Implement**

Add before `register`:

```python
@translates_okama_errors
def get_initial_investment_values(
    portfolio: dict[str, Any],
    cashflow: dict[str, Any],
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Present value (PV) and future value (FV) of the initial investment.

    PV discounts the initial investment to the historical first date using
    ``discount_rate``; FV is the nominal initial investment. Both are ``None`` if
    the strategy has no ``initial_investment``.
    """
    pf, cashflow_spec = _prepare_cashflow(portfolio, cashflow, discount_rate=discount_rate)
    pv = pf.dcf.initial_investment_pv
    fv = pf.dcf.initial_investment_fv
    return {
        "cashflow_spec": cashflow_spec.model_dump(),
        "discount_rate": value_to_json(pf.dcf.discount_rate),
        "pv": value_to_json(pv) if pv is not None else None,
        "fv": value_to_json(fv) if fv is not None else None,
    }
```

Register: `mcp.tool(get_initial_investment_values)`

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_dcf.py -q && poetry run ruff check src/okama_mcp/tools/dcf.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/dcf.py tests/test_tool_dcf.py
git commit -m "feat(dcf): add get_initial_investment_values (pv/fv)"
```

---

## Task 13: get_monte_carlo_cash_flow (summaries only)

**Files:**
- Modify: `src/okama_mcp/tools/dcf.py`
- Test: `tests/test_tool_dcf.py`

- [ ] **Step 1: Write failing test**

```python
def test_get_monte_carlo_cash_flow_bands() -> None:
    pf = _make_pf_mock_dcf()
    p1, p2, p3 = _patches(pf)
    with p1, p2, p3:
        out = dcf_tool.get_monte_carlo_cash_flow(VALID_PF_SPEC, VALID_MC_SPEC, VALID_CASHFLOW, discounting="fv")
    assert out["discounting"] == "fv"
    bands = out["cash_flow_paths"]
    assert set(bands["percentiles"].keys()) == {"5", "50", "95"}
    assert bands["n_scenarios"] == 2
    assert bands["n_months"] == 2
    pf.dcf.set_mc_parameters.assert_called_once()  # MC IS configured here
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_dcf.py::test_get_monte_carlo_cash_flow_bands -q`
Expected: FAIL — tool missing.

- [ ] **Step 3: Implement**

Extend the monte_carlo import line:

```python
from okama_mcp.tools.monte_carlo import (
    _mc_index_iso,
    _percentile_bands,
    _prepare_cashflow,
    _prepare_dcf,
    _validate_cashflow,
)
```

Add before `register`:

```python
@translates_okama_errors
def get_monte_carlo_cash_flow(
    portfolio: dict[str, Any],
    mc: dict[str, Any],
    cashflow: dict[str, Any],
    discounting: str = "fv",
) -> dict[str, Any]:
    """Monte Carlo distribution of future cash flows over time.

    Returns percentile bands of the simulated cash-flow paths (never the raw
    months x scenarios matrix), mirroring ``monte_carlo_forecast``'s wealth bands.
    """
    pf, mc_spec = _prepare_dcf(portfolio, mc, cashflow)
    mc_cf = pf.dcf.monte_carlo_cash_flow(discounting=discounting)
    return {
        "mc_spec": mc_spec.model_dump(),
        "cashflow_spec": _validate_cashflow(cashflow).model_dump(),
        "discounting": discounting,
        "cash_flow_paths": {
            "index": _mc_index_iso(mc_cf),
            "percentiles": _percentile_bands(mc_cf, mc_spec.percentiles),
            "n_scenarios": int(mc_cf.shape[1]),
            "n_months": int(mc_cf.shape[0]),
        },
    }
```

Register: `mcp.tool(get_monte_carlo_cash_flow)`

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_dcf.py -q && poetry run ruff check src/okama_mcp/tools/dcf.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/dcf.py tests/test_tool_dcf.py
git commit -m "feat(dcf): add get_monte_carlo_cash_flow (percentile bands)"
```

---

## Task 14: plots — plot_qq + plot_hist_fit (replicated, thread-safe)

**Files:**
- Modify: `src/okama_mcp/tools/plots.py`
- Test: `tests/test_tool_plots.py` (create if absent; otherwise append)

**Background:** okama's `MonteCarlo.plot_qq` / `plot_hist_fit` create figures via global `plt` (not thread-safe under FastMCP workers — same issue as `plot_transition_map`). We replicate them on an owned `make_figure()` Axes using the fitted parameters from `get_parameters_for_distribution()` and scipy.

- [ ] **Step 1: Write failing test**

Create/append `tests/test_tool_plots.py`:

```python
"""Smoke tests for plot_qq / plot_hist_fit (offline, mocked okama)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastmcp.utilities.types import Image

from okama_mcp.tools import plots as plots_tool
from okama_mcp.tools import portfolio as pf_tool


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    pf_tool.clear_cache()


PF_SPEC: dict = {"assets": ["GLD.US"], "ccy": "USD", "rebalancing_strategy": {"period": "year"}}
MC_SPEC_T: dict = {"distribution": "t", "period_years": 10, "scenarios": 50}


def _pf_with_ror() -> SimpleNamespace:
    pf = SimpleNamespace()
    pf.symbol = "pf.PF"
    pf.symbols = ["GLD.US"]
    dcf = SimpleNamespace()
    dcf.set_mc_parameters = MagicMock()
    rng = np.random.default_rng(0)
    mc = SimpleNamespace()
    mc.ror = pd.Series(rng.normal(0.005, 0.04, 120))
    mc.get_parameters_for_distribution = MagicMock(return_value=(5.0, 0.005, 0.04))
    dcf.mc = mc
    pf.dcf = dcf
    return pf


def test_plot_qq_returns_image() -> None:
    pf = _pf_with_ror()
    with (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
    ):
        out = plots_tool.plot_qq(PF_SPEC, MC_SPEC_T)
    assert isinstance(out, Image)


def test_plot_hist_fit_returns_image() -> None:
    pf = _pf_with_ror()
    with (
        patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf),
        patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"),
    ):
        out = plots_tool.plot_hist_fit(PF_SPEC, MC_SPEC_T)
    assert isinstance(out, Image)
```

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_plots.py -q`
Expected: FAIL — `plot_qq`/`plot_hist_fit` missing.

- [ ] **Step 3: Implement**

In `plots.py`, add imports at top:

```python
import numpy as np
import scipy.stats
```

and extend the monte_carlo import:

```python
from okama_mcp.tools.monte_carlo import _prepare_dcf, _prepare_mc
```

Add the two tools before `register`:

```python
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
    params = pf.dcf.mc.get_parameters_for_distribution()
    if mc_spec.distribution == "norm":
        dist_name, sparams = "norm", ()
    else:  # 'lognorm' and 't' both take a single shape param first
        dist_name, sparams = mc_spec.distribution, (params[0],)
    fig, ax = make_figure(width, height)
    scipy.stats.probplot(ror.values, dist=dist_name, sparams=sparams, plot=ax)
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
```

Register both in `register`:

```python
    mcp.tool(plot_qq)
    mcp.tool(plot_hist_fit)
```

- [ ] **Step 4: Run, verify PASS + ruff**

Run: `poetry run pytest tests/test_tool_plots.py -q && poetry run ruff check src/okama_mcp/tools/plots.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/plots.py tests/test_tool_plots.py
git commit -m "feat(plots): add plot_qq + plot_hist_fit (thread-safe replication)"
```

---

## Task 15: Register new modules

**Files:**
- Modify: `src/okama_mcp/tools/__init__.py`
- Test: `tests/test_tool_registration.py` (create) OR extend existing server/registration test if present.

- [ ] **Step 1: Write failing test**

Create `tests/test_tool_registration.py`:

```python
"""Verify all tool modules register and the expected new tools exist."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP

from okama_mcp.tools import register_all


def test_new_tools_registered() -> None:
    mcp = FastMCP("test")
    register_all(mcp)
    tools = asyncio.run(mcp.get_tools())
    names = set(tools.keys())
    expected = {
        "get_distribution_fit", "get_return_moments", "optimize_students_df",
        "get_cagr_distribution", "get_dcf_wealth_index", "get_dcf_cash_flow_ts",
        "get_dcf_wealth_with_assets", "get_survival_period",
        "get_initial_investment_values", "get_monte_carlo_cash_flow",
        "plot_qq", "plot_hist_fit",
    }
    missing = expected - names
    assert not missing, f"missing tools: {missing}"
    assert len(names) >= 45
```

(If `mcp.get_tools()` is not the correct FastMCP introspection API in the installed version, adapt to the same call the existing server smoke test uses — check `tests/` for a precedent before writing this test.)

- [ ] **Step 2: Run, verify FAIL**

Run: `poetry run pytest tests/test_tool_registration.py -q`
Expected: FAIL — new modules not registered.

- [ ] **Step 3: Implement**

In `src/okama_mcp/tools/__init__.py`, add `dcf` and `mc_diagnostics` to the import block and register them:

```python
    from okama_mcp.tools import (
        asset,
        asset_list,
        dcf,
        frontier,
        macro,
        mc_diagnostics,
        monte_carlo,
        plots,
        portfolio,
        search,
    )

    search.register(mcp)
    asset.register(mcp)
    asset_list.register(mcp)
    portfolio.register(mcp)
    monte_carlo.register(mcp)
    mc_diagnostics.register(mcp)
    dcf.register(mcp)
    frontier.register(mcp)
    macro.register(mcp)
    plots.register(mcp)
```

- [ ] **Step 4: Run, verify PASS**

Run: `poetry run pytest tests/test_tool_registration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/__init__.py tests/test_tool_registration.py
git commit -m "feat(tools): register mc_diagnostics + dcf tool modules"
```

---

## Task 16: Integration tests (live, marked) + README catalog

**Files:**
- Modify: `tests/test_integration.py` (or the file holding `integration`-marked tests — locate it first)
- Modify: `README.md`

- [ ] **Step 1: Add live smoke tests behind the marker**

Locate the existing integration test module (the 16 deselected tests). Add, using its existing portfolio/cashflow fixtures and `@pytest.mark.integration`:

```python
@pytest.mark.integration
def test_live_distribution_fit() -> None:
    from okama_mcp.tools import mc_diagnostics as diag
    out = diag.get_distribution_fit(
        {"assets": ["SPY.US", "AGG.US"], "weights": [0.6, 0.4], "ccy": "USD",
         "rebalancing_strategy": {"period": "year"}},
        {"distribution": "t", "period_years": 10, "scenarios": 200},
    )
    assert len(out["parameters"]) == 3
    assert "p-value" in out["kstest"]


@pytest.mark.integration
def test_live_dcf_survival_and_mc_cashflow() -> None:
    from okama_mcp.tools import dcf as dcf_tool
    pf = {"assets": ["SPY.US", "AGG.US"], "weights": [0.6, 0.4], "ccy": "USD",
          "first_date": "2010-01", "last_date": "2024-10", "rebalancing_strategy": {"period": "year"}}
    cf = {"type": "indexation", "initial_investment": 100_000.0, "frequency": "year",
          "amount": -5_000.0, "indexation": "inflation"}
    surv = dcf_tool.get_survival_period(pf, cf, threshold=0.0)
    assert surv["survival_period_years"] is not None
    mc_cf = dcf_tool.get_monte_carlo_cash_flow(
        pf, {"distribution": "norm", "period_years": 10, "scenarios": 100, "percentiles": [5, 50, 95]}, cf
    )
    assert set(mc_cf["cash_flow_paths"]["percentiles"].keys()) == {"5", "50", "95"}
```

- [ ] **Step 2: Run live tests once to confirm they pass with the real API**

Run: `poetry run pytest -m integration -q -k "distribution_fit or survival or mc_cashflow"`
Expected: PASS (network-dependent; retry if api.okama.io times out).

- [ ] **Step 3: Update README tool catalog**

In `README.md`, add the 12 new tools to the tool list/table in the same format as existing entries (grouped under Monte Carlo / DCF / plots). Mention `distribution_parameters` on the MCSpec example and the new `time_series_discounted_values` flag.

- [ ] **Step 4: Full suite + ruff**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: all non-integration green; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add tests/ README.md
git commit -m "test(integration): live coverage for MC/DCF tools; docs: README tool catalog"
```

---

## Self-Review

**Spec coverage:**
- distribution_parameters → Task 1 ✓
- all CashFlow strategies (already present) + time_series_discounted_values → Task 2 ✓
- discount_rate threading → Task 3 ✓
- MC diagnostics (get_parameters_for_distribution, jarque_bera, kstest, kstest_for_all_distributions, backtesting_error) → Task 5 ✓; skewness/kurtosis(+rolling) → Task 6 ✓; optimize_df_for_students → Task 7 ✓; percentile_distribution_cagr + percentile_inverse_cagr → Task 8 ✓
- DCF: wealth_index → Task 9 ✓; cash_flow_ts → Task 9 ✓; wealth_index_fv_with_assets → Task 10 ✓; survival_period_hist + survival_date_hist → Task 11 ✓; initial_investment_pv/fv → Task 12 ✓; monte_carlo_cash_flow → Task 13 ✓
- plot_qq + plot_hist_fit → Task 14 ✓
- registration → Task 15 ✓; README + integration → Task 16 ✓

**Type/name consistency:** helper names `_apply_mc_parameters`, `_prepare_mc`, `_prepare_cashflow`, `_prepare_dcf` used consistently across Tasks 3, 5–14. Tool names match Task 15's expected set. Serialization helpers (`to_json`, `series_to_json`, `dataframe_to_json`, `value_to_json`) used as defined in `serialization.py`.

**Placeholder scan:** none — every code step contains complete code. Two notes flag incremental-import handling (Tasks 5, 9) and one API-name verification (Task 15 `get_tools`) to check against the installed FastMCP before writing — these are explicit instructions, not placeholders.

**Out of scope (deferred to release):** version bump, `server.json` tool list, mcp.okama.io landing sync.
