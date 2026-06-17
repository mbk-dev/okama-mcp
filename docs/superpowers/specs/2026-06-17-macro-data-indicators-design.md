# Design: macroeconomic data & indicators (CAPE10) for okama-mcp

Date: 2026-06-17
Status: approved (design), pending spec review

## Goal

Expose okama's full macroeconomic / macro-financial surface as MCP tools, plus
market indicators (CAPE10). Today the MCP wraps only inflation and a (partly
broken) central-bank rate; the `Indicator` class and several methods on
`Inflation`/`Rate` are unreachable.

All behaviour below is grounded in the installed okama API, verified by reading
`okama/__init__.py` and `okama/macro/*` and by probing the live library
(`poetry run python`), not assumptions.

## Verified okama facts driving this design

okama macro = **3 classes**, **3 namespaces** (`ok.macro_namespaces == ['INFL',
'RATE', 'RATIO']`). All three subclass `MacroABC` and share `symbol`, `name`,
`country`, `currency`, `type`, `first_date`, `last_date`, `values_monthly`,
`describe(years=(1, 5, 10))`, `set_values_monthly(date, value)`.

- **`Inflation(symbol="RUB.INFL", first_date=None, last_date=None)`** — namespace
  `INFL` (6 symbols: `CNY/EUR/GBP/ILS/RUB/USD.INFL`). Extra properties:
  `annual_inflation_ts`, `cumulative_inflation`, `rolling_inflation` (12-month,
  needs ≥12 months of data), `purchasing_power_1000` (float).
- **`Rate(symbol="RUS_CBR.RATE", first_date=None, last_date=None)`** — namespace
  `RATE` (41 symbols). Extra property: **`values_daily`**. Real symbols are
  `RUS_CBR.RATE`, `US_EFFR.RATE`, `EU_MRO.RATE`, `EU_MLR.RATE`, `EU_DFR.RATE`,
  `UK_BR.RATE`, `ISR_IR.RATE`, `CHN_LPR1.RATE`, `CHN_LPR5.RATE`, plus deposit
  rates (`RUS_RUB/RUS_USD/RUS_EUR`), `RUONIA*`, `RUSFAR*`.
  **There is no `US.RATE` / `ECB.RATE` / `RUS.RATE`.**
- **`Indicator(symbol="USA_CAPE10.RATIO", first_date=None, last_date=None)`** —
  namespace `RATIO` (26 symbols, all CAPE10: `USA_CAPE10.RATIO`,
  `EUR_CAPE10.RATIO`, `RUS_CAPE10.RATIO`, … `{COUNTRY}_CAPE10.RATIO`). Only
  `values_monthly` beyond the shared base. Constructor rejects `INFL`/`RATE`
  namespaces.
- **`describe()`** returns a small `DataFrame` (YTD + per-horizon arithmetic
  mean / median / max / min; for `Inflation` also compound inflation, max 12m,
  purchasing power). Computed from already-fetched data.
- **Discovery already works:** `search_assets(namespace="RATIO")` returns all 26
  CAPE10; `=="RATE"` → 41; `=="INFL"` → 6. `list_namespaces(kind="macro")`
  returns the 3 macro namespaces with descriptions.

## Current state (what's wrapped) — `src/okama_mcp/tools/macro.py`

- `get_inflation(currency, first_date, last_date, include_cumulative, full)` —
  returns metadata + `values_monthly` + `annual_inflation` + `purchasing_power_1000`,
  optional `cumulative_inflation`. `currency` normalised `USD → USD.INFL`
  (**correct** — INFL symbols are bare currency codes).
- `get_central_bank_rate(country, first_date, last_date, full)` — returns
  metadata + `values_monthly` only. `country` normalised `US → US.RATE`
  (**broken** — `US.RATE` does not exist; works only when a full symbol is
  passed). Docstring examples `US.RATE / ECB.RATE / RUS.RATE` are wrong.

## Decisions (resolved with the user)

1. **Tool shape:** concept-specific tools (matches existing design), not a single
   generic dispatcher.
2. **Plots:** add a `plot_macro` line-chart tool.
3. **Rate input fix:** curated alias map (friendly `country` codes → real key
   policy-rate symbols), full symbols still pass through.
4. **`set_values_monthly` is NOT wrapped.** It mutates an instance that a
   stateless tool discards after the call (AGENTS.md: "no implicit session
   state"), so it cannot affect any output. A forecast-injection feature, if ever
   wanted, is a separate stateful design.
5. **No new namespace/symbol-listing tool** — already covered by
   `list_namespaces(kind="macro")` + `search_assets(namespace=...)`.

## Changes

### A. `src/okama_mcp/tools/macro.py`

**New helpers**

- Curated rate alias map → real key policy-rate symbols (all verified to exist):
  `US/USA → US_EFFR`, `EU/ECB → EU_MRO`, `RU/RUS → RUS_CBR`, `UK/GB → UK_BR`,
  `IL/ISR → ISR_IR`, `CN/CHN → CHN_LPR1`.
  `_normalise_rate(value)`: if `value` contains `.` → upper, as-is; elif upper
  key in alias map → `{alias}.RATE`; elif contains `_` (e.g. `RUS_CBR`,
  `RUSFAR1M`) → `{upper}.RATE`; else `{upper}.RATE` (fallback; unknown codes
  surface a translated okama error).
- `_normalise_indicator(value)`: if `.` → upper, as-is; elif contains `_`
  (e.g. `USA_CAPE10`) → `{upper}.RATIO`; else bare country code (e.g. `USA`) →
  `{upper}_CAPE10.RATIO`.
- `_describe(obj)` → `dataframe_to_json(obj.describe(), full=True)` (describe is a
  small fixed-shape table; full is fine).

**NEW `get_indicator`**
```
get_indicator(symbol="USA_CAPE10.RATIO", first_date=None, last_date=None,
              include_describe=False, full=False) -> dict
```
Builds `ok.Indicator(_normalise_indicator(symbol), ...)`. Returns `_metadata` +
`values_monthly` (+ `describe` when `include_describe`).

**`get_central_bank_rate`** — add `frequency: str = "monthly"` ("monthly" |
"daily") and `include_describe: bool = False`; switch normalisation to
`_normalise_rate`; fix docstring.
- `frequency == "daily"` → `out["values_daily"] = series_to_json(rate.values_daily, full=full)`;
  otherwise `values_monthly`. Invalid `frequency` → `OkamaMcpError`.
- `include_describe` → `out["describe"] = _describe(rate)`.

**`get_inflation`** — add `include_rolling: bool = False` and
`include_describe: bool = False`.
- `include_rolling` → `out["rolling_inflation"] = series_to_json(infl.rolling_inflation, full=full)`.
- `include_describe` → `out["describe"] = _describe(infl)`.
- Existing fields/behaviour unchanged.

### B. `src/okama_mcp/tools/plots.py`

**NEW `plot_macro`**
```
plot_macro(symbols: list[str], first_date=None, last_date=None,
           frequency="monthly", title=None,
           width=1500, height=900, save_path=None) -> Image | list[Image | str]
```
- Symbol resolution (unambiguous, by suffix): a symbol **with** a namespace
  suffix routes by it (`.INFL → Inflation`, `.RATE → Rate`, `.RATIO → Indicator`)
  and is used as-is. A symbol **without** a suffix is treated as a CAPE10 country
  code → `{CODE}_CAPE10.RATIO` (same default as `get_indicator`), so
  `plot_macro(["USA","EUR"])` plots CAPE10. Rates/inflation must be passed
  suffixed (`US_EFFR.RATE`, `USD.INFL`) — bare rate aliases are intentionally NOT
  resolved here to avoid `US`(rate) vs `USA`(CAPE10) ambiguity.
- Series: `values_daily` when `frequency == "daily"` (only valid for `.RATE`;
  a non-RATE symbol with `frequency="daily"` → `OkamaMcpError`), else
  `values_monthly`.
- Plot each as a labelled line (label = resolved symbol) on one axis via
  `make_figure` / `_plot_index_values` / `_render`; legend; title defaults to
  the comma-joined resolved symbols. Mixing namespaces is allowed (the y-axis is
  generic — values are %, rate %, or ratio), so the title carries the meaning.

### C. Registration & docs

- `macro.register` also registers `get_indicator`.
- `plots.register` also registers `plot_macro`.
- Update the README tool catalog (macro section + plot list).
- Version bump / `server.json` / `mcp.okama.io` landing sync are a **separate
  release step**, out of scope here.

## Serialization

- All series → existing `series_to_json` head/tail/summary truncation
  (`full=True` returns everything).
- `describe()` → existing `dataframe_to_json` (small fixed table).
- Metadata via the existing `_metadata(obj)` + `value_to_json` for dates.

## Testing (TDD)

Cycle per AGENTS.md: RED → verify RED → GREEN → verify GREEN → REFACTOR. Run
`poetry run pytest -q` and `poetry run ruff check .` before finishing.

- **Offline unit tests** (`tests/test_tool_macro.py`, mock `SimpleNamespace`
  objects like the existing ones — patch `ok.Inflation`/`ok.Rate`/`ok.Indicator`):
  - `get_indicator`: bare code `USA → USA_CAPE10.RATIO`; `USA_CAPE10 → …​.RATIO`;
    full symbol passes through; metadata + `values_monthly`; `include_describe`
    adds `describe`; unknown symbol → `OkamaMcpError`.
  - `get_central_bank_rate`: alias map (`US → US_EFFR.RATE`, `EU → EU_MRO.RATE`,
    `RUS → RUS_CBR.RATE`); full symbol passes through; `frequency="daily"`
    returns `values_daily`; invalid `frequency` raises; `include_describe`.
    **Existing rate tests must be updated:** the current
    `test_country_is_uppercased_and_namespace_appended` (and any asserting
    `US.RATE` / `ECB.RATE`) encode the broken `country → {code}.RATE` behaviour
    and will fail after the fix — rewrite them to assert the corrected symbols
    (`ecb → EU_MRO.RATE`, etc.).
  - `get_inflation`: `include_rolling` adds `rolling_inflation`;
    `include_describe` adds `describe`; defaults unchanged
    (`rolling_inflation`/`describe`/`cumulative_inflation` absent).
- **Plot tests** (`tests/test_tool_plots.py`): `plot_macro` returns an `Image`
  for a mocked single series; `save_path` writes a PNG and reports the path;
  `frequency="daily"` on a non-RATE symbol raises. Follow the existing mocked
  plot-test style.
- **Registration** (`tests/test_tool_macro.py` / `tests/test_tool_registration.py`):
  `get_indicator` and `plot_macro` present in `mcp.list_tools()`.
- **Integration** (existing `integration` marker, hits api.okama.io): one live
  `get_indicator("USA_CAPE10.RATIO")`, one `get_central_bank_rate("US",
  frequency="daily")`, one `plot_macro(["USA_CAPE10.RATIO","EUR_CAPE10.RATIO"])`.

## Out of scope

- `set_values_monthly` as a tool (stateless wrapper; see Decision 4).
- A separate macro namespace/symbol listing tool (already covered).
- Version bump, `server.json` tool list, landing-page sync (release step).
- `describe(years=...)` override — default `(1, 5, 10)` only.

## Result

MCP tool count: 45 → 47 (`get_indicator`, `plot_macro`). `Inflation`/`Rate` gain
their missing methods (`rolling_inflation`, `values_daily`, `describe`), the
broken rate normalisation is fixed, and CAPE10 / the entire `RATIO` namespace
becomes reachable.
