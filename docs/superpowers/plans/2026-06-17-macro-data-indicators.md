# Macro Data & CAPE10 Indicator Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose okama's full macro surface (inflation, central-bank/money-market rates, CAPE10 indicators) as MCP tools, fix the broken rate-symbol normalisation, and add a `plot_macro` chart tool.

**Architecture:** Concept-specific tools matching the existing `tools/macro.py` style (plain function params, no pydantic schemas). Add one new data tool (`get_indicator`), enrich the two existing data tools, and add one chart tool (`plot_macro`) in `tools/plots.py`. All series/frames go through the existing `okama_mcp.serialization` helpers; all tools are wrapped in `@translates_okama_errors`.

**Tech Stack:** Python ≥3.11, okama, fastmcp, pandas, matplotlib (OO API via `okama_mcp.rendering`), pytest.

## Global Constraints

- Minimum Python: `>=3.11,<4.0.0` — code must run unchanged on 3.11.
- Modern syntax: built-in generics (`list[str]`, `dict[str, Any]`), `X | None`; literals `{}`/`[]`; no mutable default args.
- Comments/docstrings in **English**; type hints on all params and returns; f-strings for messages.
- TDD per AGENTS.md: RED → verify RED → GREEN → verify GREEN → REFACTOR.
- After executable-code changes run `poetry run pytest -q`; before finishing run `poetry run ruff check .` and fix every issue.
- All temp files go in gitignored `tmp/`.
- Tools must be stateless: every call takes a full spec; no session state. (`set_values_monthly` is intentionally NOT wrapped.)
- DataFrames/Series must be normalised via `okama_mcp.serialization` before return.
- Use `poetry run python ...`; add deps with `poetry add` (none needed here).

**Verified okama facts (do not re-derive):**
- `ok.Inflation(symbol="RUB.INFL", first_date, last_date)` — props: `values_monthly`, `annual_inflation_ts`, `cumulative_inflation`, `rolling_inflation`, `purchasing_power_1000`; method `describe(years=(1,5,10))`.
- `ok.Rate(symbol="RUS_CBR.RATE", first_date, last_date)` — props: `values_monthly`, `values_daily`; method `describe(...)`. Real symbols: `US_EFFR.RATE`, `EU_MRO.RATE`, `RUS_CBR.RATE`, `UK_BR.RATE`, `ISR_IR.RATE`, `CHN_LPR1.RATE`, `RUONIA.RATE`, `RUSFAR1M.RATE`, … There is **no** `US.RATE`/`ECB.RATE`.
- `ok.Indicator(symbol="USA_CAPE10.RATIO", first_date, last_date)` — prop `values_monthly`; method `describe(...)`. Namespace `RATIO` = 26 `{COUNTRY}_CAPE10.RATIO`.
- `series_to_json(s, *, full=False)`, `dataframe_to_json(df, *, full=False)`, `value_to_json(v)` in `okama_mcp.serialization`.
- `make_figure(width_px=1500, height_px=900)` raises `ValueError` outside [300, 4000] (translated to `OkamaMcpError` by the decorator). `_plot_index_values`, `_render` live in `tools/plots.py`.

---

## File Structure

- `src/okama_mcp/tools/macro.py` — add helpers (`_describe`, `_normalise_rate`, `_RATE_ALIASES`, `_normalise_indicator`, `_resolve_plot_symbol`), enrich `get_inflation`/`get_central_bank_rate`, add `get_indicator`, register it.
- `src/okama_mcp/tools/plots.py` — add `plot_macro`, register it.
- `tests/test_tool_macro.py` — extend mocks; new/updated unit tests for the three data tools and the resolver helpers.
- `tests/test_tool_plots.py` — `plot_macro` unit tests + registration.
- `tests/test_integration_live.py` — live smoke tests for the new surface.
- `README.md` — tool-catalog update (docs only).

---

### Task 1: Fix & enrich `get_central_bank_rate` (alias map, daily, describe)

**Files:**
- Modify: `src/okama_mcp/tools/macro.py`
- Test: `tests/test_tool_macro.py`

**Interfaces:**
- Consumes: `series_to_json`, `dataframe_to_json` (serialization); `translates_okama_errors`, `OkamaMcpError` (errors).
- Produces:
  - `_RATE_ALIASES: dict[str, str]`
  - `_normalise_rate(value: str) -> str`
  - `_describe(obj: Any) -> dict[str, Any]`
  - `get_central_bank_rate(country="US", first_date=None, last_date=None, frequency="monthly", include_describe=False, full=False) -> dict[str, Any]`

- [ ] **Step 1: Update imports & extend the rate mock (test scaffolding)**

In `tests/test_tool_macro.py`, replace the existing `_make_rate_mock` with one that also carries `values_daily` and a `describe()` method:

```python
def _make_rate_mock(*, values=None, symbol="US_EFFR.RATE") -> SimpleNamespace:
    idx = pd.period_range("2024-01", periods=4, freq="M")
    values = values if values is not None else pd.Series(
        [0.0525, 0.0500, 0.0475, 0.0450], index=idx, name=symbol)
    daily_idx = pd.date_range("2024-01-01", periods=5, freq="D")
    daily = pd.Series([0.0525, 0.0525, 0.0500, 0.0500, 0.0475], index=daily_idx, name=symbol)
    desc = pd.DataFrame({symbol: [0.05, 0.0488]}, index=["mean", "median"])
    return SimpleNamespace(
        symbol=symbol,
        name="US Federal Reserve rate",
        country="USA",
        currency="USD",
        type="RATE",
        first_date=pd.Timestamp("2024-01-01"),
        last_date=pd.Timestamp("2024-04-30"),
        values_monthly=values,
        values_daily=daily,
        describe=lambda years=(1, 5, 10): desc,
    )
```

- [ ] **Step 2: Write the failing tests (replace the old `TestGetCentralBankRate`)**

Replace the whole `class TestGetCentralBankRate` block (the old tests encode the broken `US → US.RATE` behaviour) with:

```python
class TestGetCentralBankRate:
    def test_alias_maps_to_real_key_rate_symbol(self) -> None:
        rate = _make_rate_mock(symbol="EU_MRO.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate) as cls:
            macro_tool.get_central_bank_rate("ecb")
        cls.assert_called_once_with(symbol="EU_MRO.RATE", first_date=None, last_date=None)

    def test_us_alias_maps_to_effr(self) -> None:
        rate = _make_rate_mock(symbol="US_EFFR.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate) as cls:
            macro_tool.get_central_bank_rate("US")
        cls.assert_called_once_with(symbol="US_EFFR.RATE", first_date=None, last_date=None)

    def test_full_symbol_passed_through(self) -> None:
        rate = _make_rate_mock(symbol="RUSFAR1M.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate) as cls:
            macro_tool.get_central_bank_rate("RUSFAR1M.RATE", first_date="2024-01")
        cls.assert_called_once_with(symbol="RUSFAR1M.RATE", first_date="2024-01", last_date=None)

    def test_returns_monthly_by_default(self) -> None:
        rate = _make_rate_mock(symbol="US_EFFR.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate):
            out = macro_tool.get_central_bank_rate("US")
        assert out["symbol"] == "US_EFFR.RATE"
        assert out["country"] == "USA"
        assert out["values_monthly"]["values"][0] == 0.0525
        assert "values_daily" not in out
        assert "describe" not in out

    def test_frequency_daily_returns_daily_series(self) -> None:
        rate = _make_rate_mock(symbol="US_EFFR.RATE")
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate):
            out = macro_tool.get_central_bank_rate("US", frequency="daily")
        assert "values_daily" in out
        assert "values_monthly" not in out
        assert out["values_daily"]["values"][0] == 0.0525

    def test_invalid_frequency_raises(self) -> None:
        rate = _make_rate_mock()
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate):
            with pytest.raises(OkamaMcpError):
                macro_tool.get_central_bank_rate("US", frequency="weekly")

    def test_include_describe_adds_table(self) -> None:
        rate = _make_rate_mock()
        with patch("okama_mcp.tools.macro.ok.Rate", return_value=rate):
            out = macro_tool.get_central_bank_rate("US", include_describe=True)
        assert "describe" in out
        assert "columns" in out["describe"]

    def test_unknown_country_translated(self) -> None:
        with patch(
            "okama_mcp.tools.macro.ok.Rate",
            side_effect=ValueError("ZZZ.RATE is not in the list of assets"),
        ):
            with pytest.raises(OkamaMcpError):
                macro_tool.get_central_bank_rate("ZZZ")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `poetry run pytest tests/test_tool_macro.py::TestGetCentralBankRate -q`
Expected: FAIL (e.g. `get_central_bank_rate() got an unexpected keyword argument 'frequency'`, and the alias assertion fails because the current code produces `ECB.RATE`).

- [ ] **Step 4: Implement the helpers and rewrite `get_central_bank_rate`**

In `src/okama_mcp/tools/macro.py`, update the import line:

```python
from okama_mcp.errors import OkamaMcpError, translates_okama_errors
from okama_mcp.serialization import dataframe_to_json, series_to_json, value_to_json
```

Add, after `_metadata`:

```python
# Curated central-bank key policy-rate aliases (friendly code -> real okama symbol).
# Values are verified to exist in the RATE namespace. Full symbols (with a dot)
# and underscored symbols (RUS_CBR, RUSFAR1M, ...) are passed through unchanged.
_RATE_ALIASES = {
    "US": "US_EFFR", "USA": "US_EFFR",
    "EU": "EU_MRO", "ECB": "EU_MRO",
    "RU": "RUS_CBR", "RUS": "RUS_CBR",
    "UK": "UK_BR", "GB": "UK_BR",
    "IL": "ISR_IR", "ISR": "ISR_IR",
    "CN": "CHN_LPR1", "CHN": "CHN_LPR1",
}


def _normalise_rate(value: str) -> str:
    """Map a friendly central-bank code to its key-rate symbol, else add ``.RATE``."""
    value = value.strip()
    if "." in value:
        return value.upper()
    key = value.upper()
    if key in _RATE_ALIASES:
        return f"{_RATE_ALIASES[key]}.RATE"
    return f"{key}.RATE"


def _describe(obj: Any) -> dict[str, Any]:
    """Serialise a macro object's ``describe()`` table (small fixed-shape frame)."""
    return dataframe_to_json(obj.describe(), full=True)
```

Replace the existing `get_central_bank_rate` with:

```python
@translates_okama_errors
def get_central_bank_rate(
    country: str = "US",
    first_date: str | None = None,
    last_date: str | None = None,
    frequency: str = "monthly",
    include_describe: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    """Return a historical central-bank / money-market rate.

    Parameters
    ----------
    country : str, default 'US'
        A friendly central-bank code mapped to its key policy rate
        ('US'->US_EFFR, 'EU'/'ECB'->EU_MRO, 'RUS'->RUS_CBR, 'UK'/'GB'->UK_BR,
        'ISR'->ISR_IR, 'CN'/'CHN'->CHN_LPR1), or a full okama symbol
        ('US_EFFR.RATE', 'RUONIA.RATE', 'RUSFAR1M.RATE'). Use
        search_assets(namespace='RATE') to discover all 41 rate symbols.
    first_date, last_date : str, optional
        ISO 'YYYY-MM' bounds.
    frequency : {'monthly', 'daily'}, default 'monthly'
        'daily' returns the daily rate series.
    include_describe : bool, default False
        Include the describe() table (mean/median/max/min over YTD, 1/5/10y).
    full : bool, default False
        If True, return the entire series. Otherwise long series are truncated.
    """
    if frequency not in ("monthly", "daily"):
        raise OkamaMcpError("frequency must be 'monthly' or 'daily'")
    symbol = _normalise_rate(country)
    rate = ok.Rate(symbol=symbol, first_date=first_date, last_date=last_date)

    out: dict[str, Any] = _metadata(rate)
    if frequency == "daily":
        out["values_daily"] = series_to_json(rate.values_daily, full=full)
    else:
        out["values_monthly"] = series_to_json(rate.values_monthly, full=full)
    if include_describe:
        out["describe"] = _describe(rate)
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest tests/test_tool_macro.py::TestGetCentralBankRate -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add src/okama_mcp/tools/macro.py tests/test_tool_macro.py
git commit -m "fix(macro): central-bank rate alias map + daily/describe options"
```

---

### Task 2: Enrich `get_inflation` (rolling, describe)

**Files:**
- Modify: `src/okama_mcp/tools/macro.py`
- Test: `tests/test_tool_macro.py`

**Interfaces:**
- Consumes: `_describe` (Task 1), `series_to_json`.
- Produces: `get_inflation(currency="USD", first_date=None, last_date=None, include_cumulative=False, include_rolling=False, include_describe=False, full=False) -> dict[str, Any]`.

- [ ] **Step 1: Extend the inflation mock and add failing tests**

In `tests/test_tool_macro.py`, add `rolling_inflation` and `describe` to `_make_inflation_mock` (extend the `SimpleNamespace(...)` call — keep all existing fields, append these two):

```python
        rolling_inflation=pd.Series([0.011, 0.012], index=idx[-2:]),
        describe=lambda years=(1, 5, 10): pd.DataFrame(
            {symbol: [0.012, 0.07]}, index=["annual_inflation", "compound"]),
```

Add to `class TestGetInflation`:

```python
    def test_include_rolling_flag(self) -> None:
        infl = _make_inflation_mock()
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl):
            out = macro_tool.get_inflation("USD", include_rolling=True)
        assert "rolling_inflation" in out

    def test_include_describe_flag(self) -> None:
        infl = _make_inflation_mock()
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl):
            out = macro_tool.get_inflation("USD", include_describe=True)
        assert "describe" in out
        assert "columns" in out["describe"]

    def test_rolling_and_describe_absent_by_default(self) -> None:
        infl = _make_inflation_mock()
        with patch("okama_mcp.tools.macro.ok.Inflation", return_value=infl):
            out = macro_tool.get_inflation("USD")
        assert "rolling_inflation" not in out
        assert "describe" not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest tests/test_tool_macro.py::TestGetInflation -q`
Expected: FAIL (`get_inflation() got an unexpected keyword argument 'include_rolling'`).

- [ ] **Step 3: Add the two flags to `get_inflation`**

In `get_inflation`, update the signature to add `include_rolling: bool = False` and `include_describe: bool = False` (insert after `include_cumulative`), and before `return out` add:

```python
    if include_rolling:
        out["rolling_inflation"] = series_to_json(infl.rolling_inflation, full=full)
    if include_describe:
        out["describe"] = _describe(infl)
```

Also extend the docstring with one line each for the new flags (English).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `poetry run pytest tests/test_tool_macro.py::TestGetInflation -q`
Expected: PASS (all inflation tests, old + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/macro.py tests/test_tool_macro.py
git commit -m "feat(macro): rolling-inflation and describe options for get_inflation"
```

---

### Task 3: New `get_indicator` tool (CAPE10 / RATIO) + registration

**Files:**
- Modify: `src/okama_mcp/tools/macro.py`
- Test: `tests/test_tool_macro.py`

**Interfaces:**
- Consumes: `_describe` (Task 1), `series_to_json`, `_metadata`, `translates_okama_errors`.
- Produces:
  - `_normalise_indicator(value: str) -> str`
  - `get_indicator(symbol="USA_CAPE10.RATIO", first_date=None, last_date=None, include_describe=False, full=False) -> dict[str, Any]`
  - `get_indicator` registered in `macro.register`.

- [ ] **Step 1: Add an indicator mock and failing tests**

In `tests/test_tool_macro.py`, add a builder:

```python
def _make_indicator_mock(*, symbol="USA_CAPE10.RATIO") -> SimpleNamespace:
    idx = pd.period_range("2020-01", periods=4, freq="M")
    values = pd.Series([30.1, 31.4, 29.8, 32.0], index=idx, name=symbol)
    desc = pd.DataFrame({symbol: [30.8, 30.95]}, index=["mean", "median"])
    return SimpleNamespace(
        symbol=symbol,
        name="USA CAPE 10 cyclically adjusted P/E",
        country="USA",
        currency="USD",
        type="RATIO",
        first_date=pd.Timestamp("2020-01-01"),
        last_date=pd.Timestamp("2020-04-30"),
        values_monthly=values,
        describe=lambda years=(1, 5, 10): desc,
    )
```

And a test class:

```python
class TestGetIndicator:
    def test_bare_country_code_maps_to_cape10(self) -> None:
        ind = _make_indicator_mock(symbol="USA_CAPE10.RATIO")
        with patch("okama_mcp.tools.macro.ok.Indicator", return_value=ind) as cls:
            macro_tool.get_indicator("usa")
        cls.assert_called_once_with(symbol="USA_CAPE10.RATIO", first_date=None, last_date=None)

    def test_underscored_code_gets_ratio_suffix(self) -> None:
        ind = _make_indicator_mock(symbol="EUR_CAPE10.RATIO")
        with patch("okama_mcp.tools.macro.ok.Indicator", return_value=ind) as cls:
            macro_tool.get_indicator("EUR_CAPE10")
        cls.assert_called_once_with(symbol="EUR_CAPE10.RATIO", first_date=None, last_date=None)

    def test_full_symbol_passed_through(self) -> None:
        ind = _make_indicator_mock(symbol="JPN_CAPE10.RATIO")
        with patch("okama_mcp.tools.macro.ok.Indicator", return_value=ind) as cls:
            macro_tool.get_indicator("JPN_CAPE10.RATIO", first_date="2015-01")
        cls.assert_called_once_with(
            symbol="JPN_CAPE10.RATIO", first_date="2015-01", last_date=None)

    def test_returns_metadata_and_series(self) -> None:
        ind = _make_indicator_mock()
        with patch("okama_mcp.tools.macro.ok.Indicator", return_value=ind):
            out = macro_tool.get_indicator("USA")
        assert out["symbol"] == "USA_CAPE10.RATIO"
        assert out["type"] == "RATIO"
        assert out["values_monthly"]["values"][0] == 30.1
        assert "describe" not in out

    def test_include_describe_flag(self) -> None:
        ind = _make_indicator_mock()
        with patch("okama_mcp.tools.macro.ok.Indicator", return_value=ind):
            out = macro_tool.get_indicator("USA", include_describe=True)
        assert "describe" in out

    def test_unknown_symbol_translated(self) -> None:
        with patch(
            "okama_mcp.tools.macro.ok.Indicator",
            side_effect=ValueError("ZZZ_CAPE10.RATIO is not in the list of assets"),
        ):
            with pytest.raises(OkamaMcpError):
                macro_tool.get_indicator("ZZZ")
```

Also add to `class TestServerRegistration.test_phase7_tools_registered` the line:

```python
        assert "get_indicator" in names
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest tests/test_tool_macro.py::TestGetIndicator -q`
Expected: FAIL (`module 'okama_mcp.tools.macro' has no attribute 'get_indicator'`).

- [ ] **Step 3: Implement `_normalise_indicator`, `get_indicator`, register it**

In `src/okama_mcp/tools/macro.py`, add after `_normalise_rate`:

```python
def _normalise_indicator(value: str) -> str:
    """Resolve an indicator symbol; a bare country code defaults to CAPE10."""
    value = value.strip()
    if "." in value:
        return value.upper()
    if "_" in value:
        return f"{value.upper()}.RATIO"
    return f"{value.upper()}_CAPE10.RATIO"
```

Add the tool after `get_central_bank_rate`:

```python
@translates_okama_errors
def get_indicator(
    symbol: str = "USA_CAPE10.RATIO",
    first_date: str | None = None,
    last_date: str | None = None,
    include_describe: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    """Return a macro indicator series (the RATIO namespace, e.g. CAPE10).

    Parameters
    ----------
    symbol : str, default 'USA_CAPE10.RATIO'
        A full okama symbol ('USA_CAPE10.RATIO'), an indicator code without the
        namespace ('USA_CAPE10' -> '...RATIO'), or a bare country code ('USA',
        'EUR') which defaults to that country's CAPE10. Use
        search_assets(namespace='RATIO') to list all available indicators.
    first_date, last_date : str, optional
        ISO 'YYYY-MM' bounds.
    include_describe : bool, default False
        Include the describe() table (mean/median/max/min over YTD, 1/5/10y).
    full : bool, default False
        If True, return the entire series. Otherwise long series are truncated.
    """
    resolved = _normalise_indicator(symbol)
    ind = ok.Indicator(symbol=resolved, first_date=first_date, last_date=last_date)

    out: dict[str, Any] = _metadata(ind)
    out["values_monthly"] = series_to_json(ind.values_monthly, full=full)
    if include_describe:
        out["describe"] = _describe(ind)
    return out
```

In `register`, add the registration line:

```python
def register(mcp: FastMCP) -> None:
    """Register Phase 7 macro tools with the FastMCP server."""
    mcp.tool(get_inflation)
    mcp.tool(get_central_bank_rate)
    mcp.tool(get_indicator)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `poetry run pytest tests/test_tool_macro.py -q`
Expected: PASS (all macro tests incl. registration).

- [ ] **Step 5: Commit**

```bash
git add src/okama_mcp/tools/macro.py tests/test_tool_macro.py
git commit -m "feat(macro): add get_indicator tool for RATIO/CAPE10 indicators"
```

---

### Task 4: `plot_macro` chart tool + plot-symbol resolver

**Files:**
- Modify: `src/okama_mcp/tools/macro.py` (add `_resolve_plot_symbol`)
- Modify: `src/okama_mcp/tools/plots.py` (add `plot_macro`, register it)
- Test: `tests/test_tool_macro.py` (resolver unit tests), `tests/test_tool_plots.py` (chart tests)

**Interfaces:**
- Consumes: `_normalise_indicator` (Task 3), `OkamaMcpError`; `make_figure`, `_plot_index_values`, `_render`, `translates_okama_errors`, `Image`.
- Produces:
  - `_resolve_plot_symbol(value: str) -> tuple[str, str]` (returns `(resolved_symbol, namespace_tag)` where tag ∈ `{"INFL","RATE","RATIO"}`).
  - `plot_macro(symbols, first_date=None, last_date=None, frequency="monthly", title=None, width=1500, height=900, save_path=None) -> Image | list[Image | str]`, registered in `plots.register`.

- [ ] **Step 1: Write failing resolver unit tests**

In `tests/test_tool_macro.py`, add:

```python
class TestResolvePlotSymbol:
    def test_suffixed_symbols_route_by_namespace(self) -> None:
        assert macro_tool._resolve_plot_symbol("USD.INFL") == ("USD.INFL", "INFL")
        assert macro_tool._resolve_plot_symbol("us_effr.rate") == ("US_EFFR.RATE", "RATE")
        assert macro_tool._resolve_plot_symbol("USA_CAPE10.RATIO") == ("USA_CAPE10.RATIO", "RATIO")

    def test_bare_code_defaults_to_cape10(self) -> None:
        assert macro_tool._resolve_plot_symbol("USA") == ("USA_CAPE10.RATIO", "RATIO")

    def test_unknown_suffix_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            macro_tool._resolve_plot_symbol("SPY.US")
```

- [ ] **Step 2: Run resolver tests to verify they fail**

Run: `poetry run pytest tests/test_tool_macro.py::TestResolvePlotSymbol -q`
Expected: FAIL (`module ... has no attribute '_resolve_plot_symbol'`).

- [ ] **Step 3: Implement `_resolve_plot_symbol`**

In `src/okama_mcp/tools/macro.py`, add after `_normalise_indicator`:

```python
_MACRO_NAMESPACES = ("INFL", "RATE", "RATIO")


def _resolve_plot_symbol(value: str) -> tuple[str, str]:
    """Resolve a macro symbol for plotting: (symbol, namespace_tag).

    A symbol with a namespace suffix routes by it; a bare code is treated as a
    CAPE10 country code (RATIO). Non-macro symbols raise OkamaMcpError.
    """
    value = value.strip()
    if "." in value:
        symbol = value.upper()
        namespace = symbol.rsplit(".", 1)[1]
        if namespace not in _MACRO_NAMESPACES:
            raise OkamaMcpError(
                f"{value!r} is not a macro symbol "
                "(expected an .INFL / .RATE / .RATIO suffix)"
            )
        return symbol, namespace
    return _normalise_indicator(value), "RATIO"
```

- [ ] **Step 4: Run resolver tests to verify they pass**

Run: `poetry run pytest tests/test_tool_macro.py::TestResolvePlotSymbol -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Write failing `plot_macro` chart tests**

In `tests/test_tool_plots.py`, add near the other mock builders:

```python
def _make_macro_series_mock(symbol: str, *, daily: bool = False) -> SimpleNamespace:
    idx = pd.period_range("2020-01", periods=6, freq="M")
    monthly = pd.Series([30.0, 31.0, 29.5, 32.0, 33.0, 31.5], index=idx, name=symbol)
    didx = pd.date_range("2024-01-01", periods=6, freq="D")
    daily_s = pd.Series([0.05, 0.05, 0.049, 0.049, 0.048, 0.048], index=didx, name=symbol)
    return SimpleNamespace(symbol=symbol, values_monthly=monthly, values_daily=daily_s)


class TestPlotMacro:
    def test_returns_png_for_cape10(self) -> None:
        ind = _make_macro_series_mock("USA_CAPE10.RATIO")
        with patch("okama_mcp.tools.plots.ok.Indicator", return_value=ind):
            out = plots_tool.plot_macro(["USA_CAPE10.RATIO"])
        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)
        assert struct.unpack(">II", out.data[16:24]) == (1500, 900)

    def test_multiple_symbols_overlay(self) -> None:
        usa = _make_macro_series_mock("USA_CAPE10.RATIO")
        eur = _make_macro_series_mock("EUR_CAPE10.RATIO")
        with patch("okama_mcp.tools.plots.ok.Indicator", side_effect=[usa, eur]):
            out = plots_tool.plot_macro(["USA", "EUR"])
        assert isinstance(out, Image)
        assert out.data.startswith(PNG_MAGIC)

    def test_daily_frequency_on_rate(self) -> None:
        rate = _make_macro_series_mock("US_EFFR.RATE", daily=True)
        with patch("okama_mcp.tools.plots.ok.Rate", return_value=rate):
            out = plots_tool.plot_macro(["US_EFFR.RATE"], frequency="daily")
        assert isinstance(out, Image)

    def test_daily_on_non_rate_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_macro(["USA_CAPE10.RATIO"], frequency="daily")

    def test_empty_symbols_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_macro([])

    def test_invalid_frequency_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            plots_tool.plot_macro(["USA_CAPE10.RATIO"], frequency="weekly")

    def test_save_path_writes_png(self, tmp_path) -> None:
        ind = _make_macro_series_mock("USA_CAPE10.RATIO")
        target = tmp_path / "cape.png"
        with patch("okama_mcp.tools.plots.ok.Indicator", return_value=ind):
            out = plots_tool.plot_macro(["USA_CAPE10.RATIO"], save_path=str(target))
        assert isinstance(out, list) and len(out) == 2
        assert target.read_bytes().startswith(PNG_MAGIC)
```

Add `plot_macro` to the registration assertion in `TestPlotMacro`-adjacent registration test — append `"plot_macro"` to the tuple inside `test_plot_tools_registered`.

- [ ] **Step 6: Run chart tests to verify they fail**

Run: `poetry run pytest tests/test_tool_plots.py::TestPlotMacro -q`
Expected: FAIL (`module 'okama_mcp.tools.plots' has no attribute 'plot_macro'`; and `plots.ok` has no attribute because okama isn't imported yet).

- [ ] **Step 7: Implement `plot_macro`**

In `src/okama_mcp/tools/plots.py`, add to the imports block:

```python
import okama as ok
```

and:

```python
from okama_mcp.tools.macro import _resolve_plot_symbol
```

Add the tool (before `register`):

```python
@translates_okama_errors
def plot_macro(
    symbols: list[str],
    first_date: str | None = None,
    last_date: str | None = None,
    frequency: str = "monthly",
    title: str | None = None,
    width: int = 1500,
    height: int = 900,
    save_path: str | None = None,
) -> Image | list[Image | str]:
    """Line chart of one or more macro series (inflation, rate, CAPE10).

    Each symbol routes by its namespace suffix: ``.INFL`` (inflation), ``.RATE``
    (central-bank / money-market rate), ``.RATIO`` (indicator, e.g.
    ``USA_CAPE10.RATIO``). A bare code is treated as a CAPE10 country code
    (``USA`` -> ``USA_CAPE10.RATIO``). Overlay several symbols on one axis
    (e.g. ``["USA_CAPE10.RATIO", "EUR_CAPE10.RATIO"]``). ``frequency='daily'``
    is valid only for ``.RATE`` symbols. ``width``/``height``: PNG size in pixels
    (300-4000); ``save_path``: optionally also write the PNG and report the path.
    """
    if not symbols:
        raise OkamaMcpError("symbols must be a non-empty list of macro tickers")
    if frequency not in ("monthly", "daily"):
        raise OkamaMcpError("frequency must be 'monthly' or 'daily'")

    classes = {"INFL": ok.Inflation, "RATE": ok.Rate, "RATIO": ok.Indicator}
    fig, ax = make_figure(width, height)
    resolved: list[str] = []
    for raw in symbols:
        symbol, namespace = _resolve_plot_symbol(raw)
        if frequency == "daily" and namespace != "RATE":
            raise OkamaMcpError(
                f"frequency='daily' is only available for .RATE symbols, not {symbol!r}"
            )
        obj = classes[namespace](symbol=symbol, first_date=first_date, last_date=last_date)
        series = obj.values_daily if frequency == "daily" else obj.values_monthly
        x = _plot_index_values(series.index)
        ax.plot(x, series.astype(float).values, label=symbol)
        resolved.append(symbol)
    ax.set_title(title or ", ".join(resolved))
    ax.set_ylabel("Value")
    ax.legend()
    return _render(fig, save_path)
```

In `register`, add:

```python
    mcp.tool(plot_macro)
```

- [ ] **Step 8: Run chart tests to verify they pass**

Run: `poetry run pytest tests/test_tool_plots.py -q`
Expected: PASS (all plot tests incl. `TestPlotMacro` and registration).

- [ ] **Step 9: Run the full offline suite + lint**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: PASS, no ruff findings.

- [ ] **Step 10: Commit**

```bash
git add src/okama_mcp/tools/macro.py src/okama_mcp/tools/plots.py \
        tests/test_tool_macro.py tests/test_tool_plots.py
git commit -m "feat(plots): add plot_macro chart for inflation/rate/indicator series"
```

---

### Task 5: Live integration smoke tests

**Files:**
- Modify: `tests/test_integration_live.py`

**Interfaces:**
- Consumes: `get_indicator`, `get_central_bank_rate`, `plot_macro` (registered tools), the `server` fixture, `fastmcp.Client`.

- [ ] **Step 1: Add live tests**

Append to `tests/test_integration_live.py`:

```python
async def test_get_indicator_cape10_live(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "get_indicator",
            {"symbol": "USA_CAPE10.RATIO", "first_date": "2020-01", "last_date": "2020-12"},
        )
        payload = result.data
    assert payload["symbol"] == "USA_CAPE10.RATIO"
    assert payload["values_monthly"]["values"]


async def test_get_central_bank_rate_daily_live(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "get_central_bank_rate",
            {"country": "US", "frequency": "daily",
             "first_date": "2024-01", "last_date": "2024-03"},
        )
        payload = result.data
    assert payload["symbol"] == "US_EFFR.RATE"
    assert "values_daily" in payload
    assert payload["values_daily"]["values"]


async def test_plot_macro_cape10_live(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "plot_macro",
            {"symbols": ["USA_CAPE10.RATIO", "EUR_CAPE10.RATIO"],
             "first_date": "2015-01", "last_date": "2020-12"},
        )
    assert any(c.type == "image" for c in result.content)
```

- [ ] **Step 2: Run the integration tests (network required)**

Run: `poetry run pytest -m integration tests/test_integration_live.py -q -k "indicator or central_bank_rate_daily or plot_macro"`
Expected: PASS (3 tests). If api.okama.io is unreachable, note the network failure rather than treating it as a code defect.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration_live.py
git commit -m "test(integration): live coverage for get_indicator, daily rate, plot_macro"
```

---

### Task 6: Update README tool catalog (docs only)

**Files:**
- Modify: `README.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Locate the macro + plots sections in the catalog**

Run: `grep -nE "get_inflation|get_central_bank_rate|plot_assets|Macro|macro" README.md`

- [ ] **Step 2: Edit the catalog**

In the macro tool listing, update `get_central_bank_rate` to mention `frequency` (monthly/daily) + `include_describe`, update `get_inflation` to mention `include_rolling`/`include_describe`, and add a `get_indicator` row:
`get_indicator(symbol="USA_CAPE10.RATIO", ...)` — macro indicators (RATIO namespace, e.g. CAPE10 by country).

In the plots/charts listing, add:
`plot_macro(symbols, frequency="monthly", ...)` — line chart of inflation / rate / CAPE10 series (overlay multiple).

If the README states a tool count, bump it by 2 (45 → 47). This is content-only — no tests (per the TDD-skip rule for non-logic changes).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): document macro indicator + plot_macro tools"
```

---

## Self-Review notes

- **Spec coverage:** `get_indicator` (Task 3), rate daily+describe+alias fix (Task 1), inflation rolling+describe (Task 2), `plot_macro` (Task 4), suffix-based plot resolution (Task 4), integration (Task 5), README (Task 6). `set_values_monthly` and a namespace tool are out of scope per spec — no tasks, intentionally.
- **No placeholders:** every code/test step shows full code; commands have expected output.
- **Type consistency:** helper/tool names and signatures (`_normalise_rate`, `_normalise_indicator`, `_describe`, `_resolve_plot_symbol`, `get_indicator`, `plot_macro`) are identical across the tasks that define and consume them.
- **Out of scope (release step, not here):** version bump, `server.json` tool list, `mcp.okama.io` landing sync.
