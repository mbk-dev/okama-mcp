# MCP discovery and input contracts

Status: implementation authorized on 2026-10-26; Task 1 is implemented locally,
with the full-suite gate blocked by the published Planner companion (issue #6).
Tasks 2-6 have not started. Publication is not authorized.

## Intent

An assistant should discover the appropriate data series, understand a tool's
arguments, and recover from a wrong namespace without guessing JSON fields or
repeatedly trying unrelated tickers. Differences in model capability should be
handled by a clear MCP interface, rather than treated as a reason to accept a
difficult workflow.

## Evidence and limits

The 2026-10-26 investigation used checkout `6a2a7fe`, okama-mcp 2.0.0,
okama 4.0.0 and FastMCP 4.1.3. Actual MCP client calls against the local server
confirmed the following. The reporting user's model, client and server version
are still unknown; the investigation does not reproduce that exact environment.

- `list_namespaces` exists; namespace browsing is available through
  `search_assets(query="", namespace=...)`. Results are capped at 50 and there
  is no continuation parameter.
- A broad Bitcoin search omitted `BTC-USD.CC` from its returned first page,
  despite the symbol being available. Exact symbol lookup succeeded.
- The emitted `frontier` and `plan` schemas contain an unrestricted object,
  while detailed Pydantic models already exist in `schemas.py`. The same
  omission affects portfolio, cash-flow and Monte Carlo inputs, including plots
  and arrays of nested portfolios.
- `RUS_RUB.RATE` is a rate series: an asset-return call rejects it, while
  `get_central_bank_rate(country="RUS_RUB.RATE")` succeeds. Deposit return
  indexes such as `OKID.INDX` and `OKID10.INDX` are separate assets.
- `get_asset_returns(..., inflation=False)` still accesses
  `real_mean_return`, which raises. Enabling inflation allowed the same
  deposit-index/equity-index comparison to complete.

Reproduce these observations through the public MCP calls below; data-dependent
counts and rankings may change. Acceptance tests must use fixed fixtures rather
than assume a permanently fixed live catalog.

```json
{"tool":"list_namespaces","arguments":{"kind":"all"}}
{"tool":"search_assets","arguments":{"namespace":"RATE"}}
{"tool":"search_assets","arguments":{"query":"bitcoin"}}
{"tool":"search_assets","arguments":{"query":"deposit","namespace":"INDX"}}
{"tool":"get_asset_returns","arguments":{"symbols":["RUS_RUB.RATE","SPY.US"]}}
{"tool":"get_central_bank_rate","arguments":{"country":"RUS_RUB.RATE","first_date":"2020-01","last_date":"2020-12"}}
{"tool":"get_asset_returns","arguments":{"symbols":["OKID.INDX","MCFTR.INDX"],"ccy":"RUB","first_date":"2020-01","last_date":"2020-12","inflation":false}}
```

## Approach and tradeoffs

Three approaches were considered:

1. Expand descriptions only: small change, but models still lack machine-readable
   input contracts and complete catalog traversal.
2. Reuse existing Pydantic models at the MCP boundary and improve the existing
   discovery tools: recommended. This addresses the verified causes while
   preserving tool names, JSON argument structure and okama as the data source.
3. Add a separate catalog service, embedding search or an LLM-based resolver:
   larger operational surface and new ambiguity; the current evidence does not
   justify it.

The user authorized task decomposition and implementation of this plan on 2026-10-26.

## Required behavior

### Correct nominal and real return behavior

With `inflation=False, real=False`, return nominal metrics and set
`real_mean_return` to `null`, without accessing inflation-dependent properties.
With `real=True, inflation=False`, return a clear domain error before fetching
asset data. With `inflation=True`, preserve existing numerical behavior.
Document the nullable result field; do not silently enable inflation or substitute
nominal values for real values.

### Complete schemas at the MCP boundary

Publish `PortfolioSpec`, `FrontierSpec`, `MCSpec`, `CashflowSpec`, `FinPlanSpec`
and optional lists of `PortfolioSpec` as actual typed parameters. Include fields,
required values, defaults, bounds, enums, nested objects and cash-flow
discriminators. Preserve legitimate maps such as dated cash-flow amounts.

Use direct typed public signatures and the existing validation/build helpers;
internal helpers may accept models or dictionaries to preserve direct Python
callers. Do not expose a public union with an unrestricted dictionary, because
that reintroduces the ambiguous schema. Do not manually duplicate Pydantic JSON
schemas or patch private FastMCP structures. Validate recursive portfolio schemas
through both `tools/list` and `tools/call`.

### Useful search ordering and complete traversal

Keep `search_assets` and its existing filters. Add `offset: int = 0` with a
non-negative constraint. Retain `count` as the total after filtering, `results`
as the current page, and `truncated` as an indication that the page is not the
complete result set. Add `offset`, `limit`, `has_more` and nullable `next_offset`.
An offset beyond the end returns an empty page with no continuation.

For a non-empty query, rank case-insensitive exact symbol/ticker/ISIN matches,
then exact name/local-name matches, then literal prefixes, then other returned
matches. Resolve ties by normalized symbol. Rank the complete candidate set
before slicing it; an exact Bitcoin name must beat ETFs or tokens merely
containing that word. A qualified symbol should resolve within its namespace.

When `oldest_first=True`, chronological order remains primary, missing dates
remain last, and symbol breaks ties. Empty-query browsing uses symbol order.
Pagination is stateless over the current catalog, not an immutable snapshot;
document this limit. Keep the per-page ceiling at 50.

Use okama's public search/catalog functions. Inspect and handle query punctuation
explicitly: the installed namespace search uses regular-expression matching.
The MCP query is literal text, so names containing brackets or dots must not
produce regex errors or unintended matches. Do not add direct HTTP calls.

### Explain data types and route mistakes

Improve server instructions and existing tool descriptions with a compact
sequence: discover namespaces, search within a relevant namespace, verify the
symbol, then calculate. State the difference between a rate and a return index.
Do not replace a requested rate with a deposit index automatically.

Preserve `list_namespaces`' existing mapping. Add a separate `usage` mapping
keyed by namespace, with `kind` (`asset`, `macro`, or `unknown`),
`supports_asset_returns`, and a list of implemented `tools`. Derive asset
membership from okama; explicitly map only supported macro routes. An available
upstream namespace must not be advertised as supported by a nonexistent tool.
Add corresponding `namespace` and `supports_asset_returns` fields to search rows.

For macro symbols sent to asset tools, retain the rejection and add a useful
next step: `.RATE` to `get_central_bank_rate`, `.INFL` to `get_inflation`, and
`.RATIO` to `get_indicator`. Apply guidance to metadata calls as well as portfolio
and comparison calls. Keep unexpected internal errors masked.

## Constraints and non-goals

- Python `>=3.11,<4.0.0`; poetry; no new dependency is expected.
- Use the existing okama library and stateless full-spec tool contracts.
- Comments, docstrings and repository documentation are English.
- Production changes follow RED -> verified RED -> GREEN -> verified GREEN.
- Run `poetry run pytest -q` after executable changes and `poetry run ruff check .`
  before delivery. Follow the repository's limit of two failed-suite repair cycles.
- No model-specific prompts, provider switch, semantic search service, portfolio
  methodology changes, or implicit rate-to-return conversion in this scope.
- Publication, versioning and landing-page deployment are separate delivery work
  requiring the applicable authorization. Do not infer it from this planning task.

## Acceptance

A new MCP session can see and populate the actual nested input contracts. The
fixed Bitcoin fixture returns `BTC-USD.CC` first for `bitcoin`. Every filtered
fixture record is reachable through pagination with no repeats. Existing
oldest-history queries retain their meaning. Deposit-index comparisons work;
rate-to-asset mistakes explain the correct route. Nominal calculations work
without inflation data.

For model-level validation, obtain the reporter's exact model identifier/version,
MCP client/version, server version and connection method. Record known model
settings if available. Replay the same Bitcoin, deposit-index, frontier and
financial-plan tasks before and after changes; retain tool traces, failed calls
and final outcomes. Do not attribute improvement to the interface if the model,
client or data changed between the runs.
