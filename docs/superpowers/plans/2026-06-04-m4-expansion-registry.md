# M4 — Tool Expansion + MCP Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four new data tools (rolling CAGR, CAGR probability, rolling risk, dividend info — 21 → 25 tools), released as v1.2.0, then listing in the official MCP registry.

**Architecture:** Portfolio-scoped tools go into `tools/portfolio.py`, asset-scoped into `tools/asset_list.py` (existing module organization; their `register()` functions are already wired into `register_all`). No new modules. Spec: M4 section of `docs/superpowers/specs/2026-06-04-free-selfhosted-v1-design.md`.

**Verified okama 2.1.0 API (introspected + live-checked 2026-06-04):**
- `Portfolio.get_rolling_cagr(window: int = 12, real: bool = False) -> pd.DataFrame`
- `Portfolio.percentile_inverse_cagr(years: int = 1, score: float = 0) -> float` — percentile rank of a CAGR score in the historical distribution (e.g. 8.0 ⇒ 8% of historical N-year periods had CAGR below the score)
- `AssetList.get_rolling_risk_annual(window: int = 12) -> pd.DataFrame` (live-checked: DataFrame)
- `AssetList.dividend_yield` (property) — monthly LTM dividend-yield DataFrame per asset; last row = current yields (live-checked)
- `AssetList.get_dividend_mean_yield(period: int = 5) -> pd.Series` (live-checked)
- `AssetList.dividend_paying_years` / `.dividend_growing_years` (properties) — DataFrames indexed by year, per-symbol streak counts; last row = current streak (live-checked)

Dropped from the spec's candidate list: portfolio-level rolling *risk* — `get_rolling_risk_annual` does not exist on `Portfolio` in okama 2.1.0, only on `AssetList`.

**TDD:** every tool RED → GREEN → commit, mocks mirror the existing fixture styles (`tests/test_tool_portfolio.py`, `tests/test_tool_asset_list.py`).

---

### Task 1: `get_rolling_cagr` + `get_cagr_probability` (portfolio-scoped)

**Files:**
- Modify: `src/okama_mcp/tools/portfolio.py`
- Test: `tests/test_tool_portfolio.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_tool_portfolio.py`; the file already has `_make_portfolio_mock`, `VALID_SPEC`, autouse cache clearing, and the `patch(...ok.Portfolio...)` pattern — extend the mock factory with the two new methods)

In `_make_portfolio_mock`, add after `pf.get_cvar_historic = ...`:

```python
    idx_roll = pd.period_range("2011-01", periods=4, freq="M")
    pf.get_rolling_cagr = MagicMock(return_value=pd.DataFrame(
        {"pf": [0.05, 0.06, 0.055, 0.07]}, index=idx_roll))
    pf.percentile_inverse_cagr = MagicMock(return_value=8.4)
```

New test classes:

```python
class TestRollingCagr:
    def test_returns_dataframe_payload(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.get_rolling_cagr(VALID_SPEC, window_months=24, real=True)

        pf.get_rolling_cagr.assert_called_once_with(window=24, real=True)
        assert out["window_months"] == 24
        assert out["real"] is True
        assert out["rolling_cagr"]["columns"] == ["pf"]
        assert out["rolling_cagr"]["data"][0] == [0.05]

    def test_invalid_window_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            pf_tool.get_rolling_cagr(VALID_SPEC, window_months=0)


class TestCagrProbability:
    def test_returns_percentile_rank(self) -> None:
        pf = _make_portfolio_mock()
        with patch("okama_mcp.tools.portfolio.ok.Portfolio", return_value=pf), \
             patch("okama_mcp.tools.portfolio.ok.Rebalance", return_value="REB"):
            out = pf_tool.get_cagr_probability(VALID_SPEC, years=3, cagr_target=0.0)

        pf.percentile_inverse_cagr.assert_called_once_with(years=3, score=0.0)
        assert out["percentile_rank"] == 8.4
        assert out["years"] == 3
        assert out["cagr_target"] == 0.0
        assert "8.4" in out["interpretation"]
```

(If `OkamaMcpError` is not yet imported in the test file, check first — it is, via the existing error tests.)

- [ ] **Step 2: RED** — `poetry run pytest tests/test_tool_portfolio.py -q` → FAIL (`AttributeError: ... no attribute 'get_rolling_cagr'`)

- [ ] **Step 3: Implement** (append to `portfolio.py` before the Registration section)

```python
@translates_okama_errors
def get_rolling_cagr(
    portfolio: dict[str, Any],
    window_months: int = 12,
    real: bool = False,
) -> dict[str, Any]:
    """Rolling CAGR time series for the portfolio.

    ``window_months`` is the rolling window size (≥ 12 recommended by okama);
    ``real=True`` computes inflation-adjusted (real) CAGR — requires the spec
    to have ``inflation: true``.
    """
    if window_months < 1:
        raise OkamaMcpError("window_months must be a positive number of months")
    _spec, pf = _get_portfolio(portfolio)
    df = pf.get_rolling_cagr(window=window_months, real=real)
    return {
        "window_months": window_months,
        "real": real,
        "rolling_cagr": dataframe_to_json(df),
    }


@translates_okama_errors
def get_cagr_probability(
    portfolio: dict[str, Any],
    years: int = 1,
    cagr_target: float = 0.0,
) -> dict[str, Any]:
    """Percentile rank of a CAGR target in the portfolio's historical distribution.

    Answers "what share of historical ``years``-long periods ended with CAGR
    below ``cagr_target``" — e.g. with ``cagr_target=0`` this is the historical
    probability (in percent) of losing money over ``years`` years.
    """
    if years < 1:
        raise OkamaMcpError("years must be a positive integer")
    _spec, pf = _get_portfolio(portfolio)
    rank = float(pf.percentile_inverse_cagr(years=years, score=cagr_target))
    return {
        "years": years,
        "cagr_target": cagr_target,
        "percentile_rank": rank,
        "interpretation": (
            f"{rank:g}% of historical {years}-year periods had CAGR below "
            f"{cagr_target:.2%}"
        ),
    }
```

(`OkamaMcpError` must be imported in portfolio.py — check; the module already imports from `okama_mcp.errors`.)

- [ ] **Step 4: GREEN** — targeted tests pass.

- [ ] **Step 5: Register + full gates + commit**

Add to `register()` in portfolio.py: `mcp.tool(get_rolling_cagr)` and `mcp.tool(get_cagr_probability)`. Extend the existing `TestServerRegistration` test in `tests/test_tool_portfolio.py` with the two new names.

```bash
poetry run pytest -q && poetry run ruff check .
git add src/okama_mcp/tools/portfolio.py tests/test_tool_portfolio.py
git commit -m "feat(tools): get_rolling_cagr + get_cagr_probability"
```

---

### Task 2: `get_rolling_risk` + `get_dividend_info` (asset-scoped)

**Files:**
- Modify: `src/okama_mcp/tools/asset_list.py`
- Test: `tests/test_tool_asset_list.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_tool_asset_list.py`; mirror its existing mock/patch style — read the file first and reuse its AssetList mock factory if present, else build a `SimpleNamespace`)

```python
class TestRollingRisk:
    def test_returns_dataframe_payload(self) -> None:
        idx = pd.period_range("2021-01", periods=4, freq="M")
        al = SimpleNamespace()
        al.get_rolling_risk_annual = MagicMock(return_value=pd.DataFrame(
            {"SPY.US": [0.15, 0.16, 0.14, 0.15], "BND.US": [0.05, 0.05, 0.06, 0.05]},
            index=idx))
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=al):
            out = al_tool.get_rolling_risk(["SPY.US", "BND.US"], "USD", window_months=24)

        al.get_rolling_risk_annual.assert_called_once_with(window=24)
        assert out["window_months"] == 24
        assert out["rolling_risk_annual"]["columns"] == ["SPY.US", "BND.US"]

    def test_empty_symbols_raises(self) -> None:
        with pytest.raises(OkamaMcpError):
            al_tool.get_rolling_risk([], "USD")


class TestDividendInfo:
    def test_returns_compact_dividend_summary(self) -> None:
        idx = pd.period_range("2024-01", periods=3, freq="M")
        al = SimpleNamespace()
        al.dividend_yield = pd.DataFrame(
            {"SPY.US": [0.013, 0.0125, 0.012], "VNQ.US": [0.039, 0.0385, 0.0385]},
            index=idx)
        al.get_dividend_mean_yield = MagicMock(return_value=pd.Series(
            {"SPY.US": 0.0140, "VNQ.US": 0.0364}))
        years_idx = [2023, 2024]
        al.dividend_paying_years = pd.DataFrame(
            {"SPY.US": [9, 10], "VNQ.US": [9, 10]}, index=years_idx)
        al.dividend_growing_years = pd.DataFrame(
            {"SPY.US": [8, 9], "VNQ.US": [2, 0]}, index=years_idx)
        with patch("okama_mcp.tools.asset_list.ok.AssetList", return_value=al):
            out = al_tool.get_dividend_info(["SPY.US", "VNQ.US"], "USD")

        assert out["ltm_dividend_yield"] == {"SPY.US": 0.012, "VNQ.US": 0.0385}
        assert out["mean_yield_5y"] == {"SPY.US": 0.0140, "VNQ.US": 0.0364}
        assert out["paying_years_streak"] == {"SPY.US": 10, "VNQ.US": 10}
        assert out["growing_years_streak"] == {"SPY.US": 9, "VNQ.US": 0}
        al.get_dividend_mean_yield.assert_called_once_with(period=5)
```

(Add the imports the file is missing: `SimpleNamespace`, `MagicMock` — check first.)

- [ ] **Step 2: RED** — `poetry run pytest tests/test_tool_asset_list.py -q` → FAIL (no such attributes)

- [ ] **Step 3: Implement** (append to `asset_list.py`)

```python
@translates_okama_errors
def get_rolling_risk(
    symbols: list[str],
    ccy: str,
    window_months: int = 12,
    first_date: str | None = None,
    last_date: str | None = None,
) -> dict[str, Any]:
    """Rolling annualized risk (std of monthly returns) for each asset."""
    if window_months < 1:
        raise OkamaMcpError("window_months must be a positive number of months")
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation=False)
    df = al.get_rolling_risk_annual(window=window_months)
    return {
        "currency": ccy,
        "window_months": window_months,
        "rolling_risk_annual": dataframe_to_json(df),
    }


@translates_okama_errors
def get_dividend_info(
    symbols: list[str],
    ccy: str,
    first_date: str | None = None,
    last_date: str | None = None,
) -> dict[str, Any]:
    """Dividend summary per asset: current LTM yield, 5-year mean yield,
    and the current streaks of dividend-paying / dividend-growing years."""
    al = _build_asset_list(symbols, ccy, first_date, last_date, inflation=False)
    ltm = al.dividend_yield.iloc[-1]
    mean5 = al.get_dividend_mean_yield(period=5)
    paying = al.dividend_paying_years.iloc[-1]
    growing = al.dividend_growing_years.iloc[-1]

    def _series_dict(s: Any) -> dict[str, Any]:
        return {str(k): value_to_json(v) for k, v in s.items()}

    return {
        "currency": ccy,
        "ltm_dividend_yield": _series_dict(ltm),
        "mean_yield_5y": _series_dict(mean5),
        "paying_years_streak": {str(k): int(v) for k, v in paying.items()},
        "growing_years_streak": {str(k): int(v) for k, v in growing.items()},
    }
```

Check imports in asset_list.py: needs `dataframe_to_json`, `value_to_json` from `okama_mcp.serialization`, `OkamaMcpError` — add what's missing.

- [ ] **Step 4: GREEN**, then register both in `asset_list.py`'s `register()` and extend its registration test (if the file has one; otherwise the global count check in Task 3 covers it).

- [ ] **Step 5: Full gates + commit**

```bash
poetry run pytest -q && poetry run ruff check .
git add src/okama_mcp/tools/asset_list.py tests/test_tool_asset_list.py
git commit -m "feat(tools): get_rolling_risk + get_dividend_info"
```

---

### Task 3: README catalog + live integration tests

**Files:**
- Modify: `README.md`
- Test: `tests/test_integration_live.py`

- [ ] **Step 1: README** — add rows to the existing tables:

To "### Portfolio backtest":

```markdown
| `get_rolling_cagr(portfolio, window_months=12, real=False)` | Rolling CAGR time series (optionally inflation-adjusted). |
| `get_cagr_probability(portfolio, years, cagr_target)` | Historical probability of CAGR below a target (e.g. of a loss) over N-year periods. |
```

To "### Single asset & comparisons":

```markdown
| `get_rolling_risk(symbols, ccy, window_months=12)` | Rolling annualized risk per asset. |
| `get_dividend_info(symbols, ccy, ...)` | LTM dividend yield, 5y mean yield, paying/growing streaks per asset. |
```

- [ ] **Step 2: Live tests** (append to `tests/test_integration_live.py`, mirror existing style)

```python
async def test_rolling_cagr_and_probability_live(server) -> None:
    spec = {
        "assets": ["SPY.US", "BND.US"],
        "weights": [0.6, 0.4],
        "ccy": "USD",
        "first_date": "2010-01",
        "last_date": "2024-12",
        "rebalancing_period": "year",
        "inflation": True,
    }
    async with Client(server) as client:
        rolling = (await client.call_tool(
            "get_rolling_cagr", {"portfolio": spec, "window_months": 36})).data
        prob = (await client.call_tool(
            "get_cagr_probability", {"portfolio": spec, "years": 3, "cagr_target": 0.0})).data
    assert rolling["rolling_cagr"]["columns"]
    assert len(rolling["rolling_cagr"]["index"]) > 50
    assert 0.0 <= prob["percentile_rank"] <= 100.0


async def test_dividend_info_live(server) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "get_dividend_info",
            {"symbols": ["SPY.US", "VNQ.US"], "ccy": "USD",
             "first_date": "2015-01", "last_date": "2024-12"},
        )
        payload = result.data
    assert 0.0 < payload["ltm_dividend_yield"]["VNQ.US"] < 0.15
    assert payload["paying_years_streak"]["SPY.US"] >= 1
```

Run: `poetry run pytest -m integration -q` → all PASS (9 expected: 7 + 2).

- [ ] **Step 3: Full gates + commit**

```bash
poetry run pytest -q && poetry run ruff check .
git add README.md tests/test_integration_live.py
git commit -m "docs+test: catalog rows and live coverage for the four new tools"
```

---

### Task 4: Release v1.2.0

- [ ] **Step 1:** `pyproject.toml`: `version = "1.2.0"`.
- [ ] **Step 2:** Commit `chore: release 1.2.0` (body: four new data tools — rolling CAGR/risk, CAGR probability, dividend info; 25 tools total), push main.
- [ ] **Step 3:** `git tag v1.2.0 && git push origin v1.2.0`; watch the release workflow (`gh run watch ... --exit-status`).
- [ ] **Step 4:** Verify PyPI serves 1.2.0; `uvx okama-mcp@1.2.0 --help` exits 0.
- [ ] **Step 5:** Offer the user a manual hands-on test (AGENTS.md rule): restart session, ask e.g. "какова историческая вероятность убытка по портфелю 60/40 на горизонте 3 года?" (get_cagr_probability) and "дивидендная сводка по SPY.US, VNQ.US, SCHD.US" (get_dividend_info).

---

### Task 5: Official MCP registry listing

Research-first task — the procedure must be verified online at execution time, not from memory.

- [ ] **Step 1: Research.** Find the current official MCP registry publish procedure (registry.modelcontextprotocol.io / github.com/modelcontextprotocol/registry docs): required `server.json` schema, the publisher CLI, namespace rules (likely `io.github.mbk-dev/okama-mcp`), and the authentication method (likely interactive GitHub auth).
- [ ] **Step 2: Prepare.** Create `server.json` at the repo root per the verified schema, referencing the PyPI package `okama-mcp` (version 1.2.0), repository URL, and the stdio transport. Validate with the registry's validator if one exists.
- [ ] **Step 3: Publish.** If authentication is interactive (GitHub OAuth/device flow) — STOP and hand the exact commands to the user to run (`! <command>` in the session), then verify the listing appears in the registry.
- [ ] **Step 4: Commit** `server.json` (+ README badge/mention if appropriate) and push.

---

## Final verification (whole milestone)

- [ ] 25 tools registered (`mcp.list_tools()` count)
- [ ] `poetry run pytest -q` + ruff clean; `pytest -m integration -q` green (9 tests)
- [ ] CI green; PyPI 1.2.0; tag v1.2.0
- [ ] okama-mcp visible in the official MCP registry
- [ ] User confirms the new tools answer real questions in a live session
