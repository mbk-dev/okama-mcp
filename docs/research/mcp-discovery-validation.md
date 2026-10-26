# MCP discovery and input-contract validation

Date: 2026-10-26. Branch: `ответ-пользователю-mcp`; base: `6a2a7fe`.
Tracker: [epic #9](https://github.com/mbk-dev/okama-mcp/issues/9), tasks #10–#15.
The initial implementation was local and uncommitted. On 2026-10-26 the owner
authorized commit, PR, merge and release; publication evidence is tracked in
[3.0.0 validation](../releases/3.0.0-validation.md). Reporter-specific model testing is pending their model/client details.

## Implemented behavior

- Nominal returns work with `inflation=false`; `real_mean_return` is null. The
  contradictory `real=true` combination fails before asset construction.
- Every core financial input exposes its Pydantic fields in MCP `tools/list`,
  including recursive portfolios, stages, all five cash-flow variants, Monte
  Carlo settings and optional arrays. Valid existing JSON arguments still work.
- Search ranks exact identifiers, exact names, prefixes and other matches before
  pagination. Scoped punctuation is literal. `oldest_first` retains chronological
  priority. Pages expose `offset`, `limit`, `has_more`, `next_offset`; `count`
  remains the filtered total. Stable symbol ties prevent upstream row-order drift.
- Namespace descriptions are preserved; additive `usage` and search-row fields
  distinguish assets, macro series and unknown capabilities. Known macro inputs
  to asset tools receive a safe next-call correction through MCP error masking.
  Unexpected backend details remain masked; no financial series is substituted.
- `AGENTS.md` now requires upstream okama bugs and enhancement opportunities to
  be reported in GitHub Issues after checking duplicates.

## Environment and test prerequisite

Python 3.11, okama-mcp 2.0.0 source checkout, okama 4.0.0, FastMCP 4.1.3,
Pydantic 2.14.1, pandas 3.1.0, numpy 2.4.6, scipy 1.17.1, installed
okama-planner 0.4.1. No private client database was used.

The repository's `.github/workflows/ci.yml` and `docs/planner.md` explicitly use
public Planner source commit `588be5855cfaebddb6725c3f4f4126a3fda72a56` for development
acceptance. That exact source was extracted to `tmp/planner-companion` and the
full suite ran with its `src` directory on `PYTHONPATH`. No manifest or installed
package was changed, and no failing privacy test was excluded.

```bash
PYTHONPATH="$PWD/tmp/planner-companion/src:$PWD/src" poetry run pytest -q
poetry run ruff check .
git diff --check
PYTHONPATH="$PWD/tmp/planner-companion/src:$PWD/src" poetry run pytest -q -m integration tests/test_mcp_discovery_integration.py
```

The initial installed-package-only run had 35 pre-existing failures because both
published Planner 0.4.0 and 0.4.1 lack `okama_planner.ai`, tracked in
[okama-mcp#6](https://github.com/mbk-dev/okama-mcp/issues/6). The earlier decision to
stop overlooked the documented CI companion route. It was corrected before
Tasks 2–6; #6 remains a published-package reproducibility issue, not a claim that
the installed package now passes all development checks.

## Acceptance evidence

- TDD: nominal-return regressions failed before the fix; MCP error-visibility
  tests caught incorrect FastMCP exception inheritance before correction.
- Core schemas: 5 RED failures; remaining typed contracts/cash flows: 6 RED
  failures. Fixed-data search and pagination: 5 RED failures; namespace/routing:
  14 RED failures. Each group passed after implementation.
- Full CI-equivalent suite after Tasks 2–3: 351 passed; after search: 357 passed;
  after namespace routing: 371 passed. **Final: 374 passed, 35 opt-in integration
  tests deselected**, including three additional invalid-input boundary cases.
  Ruff and `git diff --check` pass. The final stdio/HTTP rerun is **2 passed**.
- Live acceptance: **9 passed**, including real subprocess stdio and HTTP
  `tools/list`/`tools/call`. This covers Bitcoin, qualified symbol, ISIN, Russian
  name, full rate-catalog traversal, nominal deposit/equity-index returns, macro
  recovery, multi-stage financial plan, Monte Carlo, optional portfolio arrays,
  nested portfolio analysis, explicit 0–1 frontier bounds and PNG image content.
- Live first attempt: 6 passed/3 failed. Cash-flow fixtures omitted required
  `initial_investment` and `frequency`; these were corrected. Restrictive
  frontier bounds revealed the separate upstream failure below. No production
  code relaxes bounds to make the test pass.
- All five cash-flow variants are tested through MCP with controlled backend
  inputs. Actual wire calls verify PNG blocks and typed nested objects, not just
  JSON-schema appearance. Invalid weights, bounds and extra fields are rejected
  before tool calculation.
- Reporter-model success rate and tool-call count have **not** been measured.
  Deterministic and transport tests do not establish universal model performance.

## Independent review status

Earlier bounded external attempts ended without a verdict (six-turn cap, then
120- and 180-second deadlines); they are retained as failed attempts. A fresh
Grok4.6 review at medium reasoning completed normally on 2026-10-26, session
`01a1772c-9413-78c0-96c2-323efb0db81d`, with **no material findings**. It reviewed
all production changes and the core new contract tests from the supplied diff.
Fresh subscription usage was 70%; it had read-only permissions and no delegation.
The parent checked its conclusions against source and a fresh 374-test pass.

## Upstream findings and limitations

1. [okama#131](https://github.com/mbk-dev/okama/issues/131): namespace-scoped
   queries interpret punctuation as regex; `[` raises ArrowInvalid. MCP uses
   okama's public namespace catalog and applies literal filtering before ranking.
2. [okama#132](https://github.com/mbk-dev/okama/issues/132): with SPY.US/GLD.US,
   USD, 2015-01–2020-12 and weights bounded to 20–80%, both frontier modes request
   infeasible CAGR targets. Direct okama reproduction confirms this independently
   of MCP. **Unfixed upstream**; the successful wire fixture uses explicit 0–1
   bounds. Do not infer that restrictive bounds are generally accepted by okama.
3. [okama#133](https://github.com/mbk-dev/okama/issues/133): rebalancing event
   construction emits pandas compatibility warnings for an integer index and
   string assignment into a float Series. Reproduced with synthetic returns and
   no network. Calculations currently complete; the upstream issue tracks the
   future compatibility risk.

Catalog order is stable for a fixed catalog; updates between page calls can move
boundaries. Optional namespace support is reported only when known. The public
registry has 52 tools and approximately 259 KB of serialized input schemas in
this environment; client-specific context and schema handling remain to be tested.

## Manual client check

After the Poetry-to-uv migration, the equivalent current source commands are below.
The historical validation commands above retain the tooling actually used for that run.

From the built task worktree, connect a client using:

```bash
uv run okama-mcp stdio
```

For HTTP, start `uv run okama-mcp http --host 127.0.0.1 --port 8765` and connect
the client to `http://127.0.0.1:8765/mcp`. These commands exercise the local source;
a remote published server has not received these changes.

1. Inspect `build_efficient_frontier`, `finplan_forecast` and `monte_carlo_forecast`
   in `tools/list`: fields and nested variants must be visible.
2. Call `search_assets(query="bitcoin")`: BTC-USD.CC should rank first. Browse
   `search_assets(namespace="RATE", limit=7)` using `next_offset` until complete.
3. Call `get_asset_returns` with the following input. Expect nominal metrics and
   `real_mean_return: null`; with inflation enabled the nominal asset CAGR values
   should agree for the same available historical window.

```json
{"symbols":["OKID.INDX","MCFTR.INDX"],"ccy":"RUB","first_date":"2020-01","last_date":"2020-12","inflation":false}
```

4. Deliberately call `get_asset_info(symbol="RUS_RUB.RATE")`. Expect a correction
   naming `get_central_bank_rate`; calling it with `country="RUS_RUB.RATE"` should
   return the macro series. No index is silently substituted.
5. Build a small frontier with `assets=["SPY.US","GLD.US"]`, `ccy="USD"`,
   `first_date="2015-01"`, `last_date="2020-12"`, `n_points=3`,
   `bounds=[[0,1],[0,1]]`. Check the upstream limitation before trying narrower bounds.
6. Submit a two-stage plan with each stage holding this portfolio for one year,
   `initial_investment=1000`, `discount_rate=0`, `scenarios=20`, `random_seed=42`.
   Omit cash flows for a minimal plan; if adding them, use the required fields in
   the emitted cash-flow variant schema. Request a portfolio chart and verify a
   PNG image is returned.

Public input fixtures and transport setup are in
`tests/test_mcp_discovery_integration.py`. Raw logs, initial failures, direct
upstream probes and review receipts are retained under
`tmp/mcp-discovery-execution/` until delivery; they are not packaged as source.
