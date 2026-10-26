# MCP Discovery and Input Contracts Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` for sequential
> implementation, or `superpowers:subagent-driven-development` if that execution
> method is selected. Follow the subscription-routing policy before delegation.
> The user authorized task decomposition and implementation on 2026-10-26.
> The owner additionally authorized commit, PR, merge and publication on 2026-10-26.

**Goal:** Make asset discovery and complex MCP inputs usable without guessing,
and fix the confirmed nominal-return failure.

**Architecture:** Publish the existing Pydantic contracts through typed public
tool signatures. Improve the current search and namespace tools using okama's
public functions; retain full-spec stateless calls and existing financial logic.

**Tech Stack:** Python, poetry, FastMCP, Pydantic v2, okama, pytest, ruff.

**Spec:** [MCP discovery and input contracts](../specs/2026-10-26-mcp-discovery-contracts-design.md).

## Global constraints

- Python `>=3.11,<4.0.0`; no new dependency is expected.
- English comments, docstrings and documentation; temporary artifacts under `tmp/`.
- TDD for production changes. Verify failures before implementation.
- Preserve tool names and valid JSON input shapes. Keep successful default
  numerical behavior. Describe the nullable real-return result explicitly.
- Use okama, never direct HTTP reimplementations of its API.
- Run `poetry run pytest -q` after executable changes and `poetry run ruff check .`.
  Stop after the repository's two unsuccessful failed-suite repair cycles.
- Review completed logical changes separately. Commit/push/release only under
  the applicable user authorization; the owner approved delivery after reviewing the local results.

## Review focus

1. Recursive portfolios and discriminated cash flows must remain callable through
   MCP, not merely appear in `tools/list` (Tasks 2-3).
2. Null optional arguments, omitted defaults and existing dictionary calls must
   retain their meaning (Tasks 2-3).
3. Search punctuation, missing metadata, equal dates and changing upstream row
   order must not break deterministic ranking/pagination (Task 4).
4. New upstream macro namespaces must not imply unsupported tool capability;
   rate suggestions must not silently substitute an index (Task 5).
5. `inflation=False` must not touch real-return properties or fetch inflation;
   contradictory `real=True` must fail clearly (Task 1).

## Sequence and deliverables

Tracker: [Improve MCP discovery and input contracts (#9)](https://github.com/mbk-dev/okama-mcp/issues/9).

| Task | Issue | Status on 2026-10-26 |
| --- | --- | --- |
| 1 | [Fix nominal returns (#10)](https://github.com/mbk-dev/okama-mcp/issues/10) | Implemented and verified; delivery receipt in #9 |
| 2 | [Expose core schemas (#11)](https://github.com/mbk-dev/okama-mcp/issues/11) | Implemented and verified; delivery receipt in #9 |
| 3 | [Expose remaining typed inputs (#12)](https://github.com/mbk-dev/okama-mcp/issues/12) | Implemented and verified; delivery receipt in #9 |
| 4 | [Rank and paginate search (#13)](https://github.com/mbk-dev/okama-mcp/issues/13) | Implemented and verified; delivery receipt in #9 |
| 5 | [Explain namespace capabilities (#14)](https://github.com/mbk-dev/okama-mcp/issues/14) | Implemented and verified; delivery receipt in #9 |
| 6 | [Validate MCP transports (#15)](https://github.com/mbk-dev/okama-mcp/issues/15) | Tests and review complete; delivery receipt in #9 |

Receipt: [Combined validation and upstream limitations](../../research/mcp-discovery-validation.md).

First deliver Tasks 1-3: a working nominal-return call and complete schemas.
Then deliver Tasks 4-5: discovery and recovery improvements. Task 6 validates the
combined behavior. Tasks 1 and 4 are independently implementable, but one writer
per worktree remains mandatory. Tasks 2 and 3 share types and should be sequential.

### Task 1 — Fix returns without inflation (P1)

**Files:** `src/okama_mcp/tools/asset_list.py`, `src/okama_mcp/errors.py`, `tests/test_tool_asset_list.py`,
`README.md`.

**Interface:** Keep `get_asset_returns` arguments. Return
`real_mean_return: dict[str, float] | None`; `None` means inflation was disabled.

- [x] Add `test_nominal_returns_without_inflation` using a fake whose
  `real_mean_return` property raises if accessed. Assert nominal metrics remain
  correct and `real_mean_return is None`.
- [x] Add `test_real_returns_require_inflation`: assert a clear `OkamaMcpError`
  for `real=True, inflation=False` and that the asset constructor was not called.
  Retain a test for `inflation=True` and the existing real-return mapping.
- [x] Run `poetry run pytest -q tests/test_tool_asset_list.py -k 'returns'`;
  confirm the new cases fail for the intended reasons.
- [x] Add the early contradictory-input check and conditional property access;
  document the result field. Re-run the focused tests, then the required suite.
- [x] Review the diff and record the validated result before moving on.
- [x] Restore the documented CI-equivalent gate using the pinned public Planner
  source; retain #6 for published-package reproducibility. Local behavior is verified; the task stays open.

### Task 2 — Publish portfolio, frontier and plan schemas (P1)

**Files:** `src/okama_mcp/schemas.py`,
`src/okama_mcp/tools/{portfolio,frontier,finplan}.py`,
new `tests/test_mcp_input_contracts.py`, existing corresponding tool tests.

**Interface:** Public parameters `portfolio: PortfolioSpec`,
`frontier: FrontierSpec`, `plan: FinPlanSpec`. Internal validation/build helpers
may accept their model or `dict[str, Any]`; the exposed contract has no dict escape.

- [x] Add MCP `list_tools` tests that resolve `$ref` and assert `assets`,
  `weights`, `ccy`, `bounds`, `n_points`, `stages` and nested stage portfolios;
  assert required fields, the 2..200 frontier point range, defaults and
  `additionalProperties: false` on closed spec objects.
- [x] Add real MCP calls backed by offline okama fakes: minimal valid inputs,
  nested portfolios, omitted optional fields, and invalid bounds/weights/unknown
  fields. Assert validation failures occur before calculation and successful
  calls preserve outputs. Retain existing direct dictionary-call tests.
- [x] Run `poetry run pytest -q tests/test_mcp_input_contracts.py`; verify RED.
- [x] Replace public dict annotations with existing model types and make minimal
  helper adjustments. Expand field descriptions where defaults or units are
  currently unclear. Preserve recursive models and current cache keys.
- [x] Run the contract and affected tool tests, then the required suite.
  Review the emitted schemas and actual successful calls together.

### Task 3 — Cover Monte Carlo, cash flows, comparisons and plots (P1)

**Files:** `src/okama_mcp/tools/{monte_carlo,mc_diagnostics,dcf,asset_list,plots}.py`,
`src/okama_mcp/schemas.py`, `tests/test_mcp_input_contracts.py`, existing tool tests.

**Interface:** Use `MCSpec`, `CashflowSpec`, `PortfolioSpec`, `FrontierSpec`,
`FinPlanSpec` and `list[PortfolioSpec] | None` for their corresponding parameters.
Preserve each parameter's existing optionality and default.

- [x] Extend the registry-wide contract test to all affected tools, including
  schemas inside arrays and nullable alternatives. Assert cash-flow variants
  have an effective discriminator and their required variant fields.
- [x] Add MCP calls for every cash-flow variant using offline fakes, optional
  `None`, nested portfolio lists, and representative plot calls. Assert image
  result blocks still work; do not convert plot outputs to generic dictionaries.
- [x] Verify RED with `poetry run pytest -q tests/test_mcp_input_contracts.py`.
- [x] Apply the typed signatures and minimal helper updates; preserve arbitrary
  date/value maps where they are valid data. Leave already-typed Planner tools
  intact and include them in registry checks when the companion is available.
- [x] Verify the targeted cases and required full suite. Review for unrestricted
  objects only where a real mapping is intentional, and record schema-size growth.

### Task 4 — Rank search results and support pagination (P2)

**Files:** `src/okama_mcp/tools/search.py`, `tests/test_tool_search.py`, `README.md`.

**Interface:** Append `offset: int = 0` to `search_assets`. Return existing fields
plus `offset`, `limit`, `has_more`, `next_offset: int | None` as specified in the design.

- [x] Build a deterministic fixture with more than 50 rows, Bitcoin after row
  50, similarly named funds/tokens, duplicate first dates, null metadata and
  bracket/dot-containing names. Assert exact symbol/ticker/ISIN, then exact name,
  then prefixes rank ahead of substring candidates; `bitcoin` returns
  `BTC-USD.CC` first. Assert explicit namespace filtering is respected.
- [x] Add pagination tests covering filter-before-count, rank-before-slice,
  stable order after shuffled source rows, full traversal without repeats,
  negative/out-of-range offsets, limit boundaries and terminal empty pages.
  Preserve the existing oldest-ETF test and add deterministic ties/missing dates.
- [x] Run `poetry run pytest -q tests/test_tool_search.py`; verify RED.
- [x] Implement deterministic ordering and slicing. For namespace-scoped literal
  search, use the public namespace catalog and literal comparisons, avoiding the
  installed library's implicit regex behavior. Keep unscoped search through
  `ok.search`; route qualified symbols to their namespace for exact matching.
- [x] If live unscoped search omits an exact candidate before local ranking,
  report that as an upstream limitation and add a bounded targeted namespace
  lookup through okama; do not claim that reordering alone restores missing rows.
- [x] Verify focused tests, required suite and documented page semantics.
  Compare broad Bitcoin, exact ticker, ISIN, Russian-name and oldest-ETF calls.

### Task 5 — Explain namespaces and recover from wrong data types (P2)

**Files:** `src/okama_mcp/server.py`, `src/okama_mcp/tools/{search,macro}.py`,
`src/okama_mcp/errors.py`, `tests/test_tool_search.py`, `tests/test_tool_macro.py`,
`tests/test_errors.py`, `tests/test_mcp_input_contracts.py`, `README.md`.

**Interface:** Preserve `list_namespaces(...)["namespaces"]`; add `usage` with
`kind`, `supports_asset_returns`, and implemented `tools` per namespace. Add
`namespace` and `supports_asset_returns` to search rows. Preserve domain-error
rejections while appending the appropriate next call.

- [x] Add tests for asset/macro/unknown namespaces, the existing mapping shape,
  search-row metadata, and an upstream namespace without an implemented route.
- [x] Add actual MCP error tests for `.RATE`, `.INFL` and `.RATIO` in asset
  contexts, including `get_asset_info`. Assert actionable guidance survives
  `mask_error_details=True`; unexpected errors remain masked. Assert no automatic
  rate-to-index substitution occurs.
- [x] Run the focused search/macro/error/contract tests and verify RED.
- [x] Implement additive capability metadata and clear errors. Update server
  instructions with discovery-first guidance and examples distinguishing
  `RUS_RUB.RATE` from `OKID.INDX`. Replace stale fixed catalog counts in descriptions
  with discovery instructions. Do not add a redundant new catalog service/tool.
- [x] Verify focused cases and the required full suite; review README examples
  and tool descriptions against the actual emitted schema.

### Task 6 — Combined acceptance and delivery preparation (P2)

**Files:** new `tests/test_mcp_discovery_integration.py`,
new `docs/research/mcp-discovery-validation.md`, relevant `examples/` fixtures.

- [x] Add marked, opt-in live integration cases for namespace traversal, Bitcoin
  discovery, deposit-index returns with inflation on/off, and rate error recovery.
  Keep fixed-data/offline tests as the deterministic correctness gate.
- [x] Run `poetry run pytest -q` and `poetry run ruff check .` after implementation.
  Run the bounded live checks with
  `poetry run pytest -q -m integration tests/test_mcp_discovery_integration.py`.
- [x] Start `poetry run okama-mcp stdio` from this built poetry environment and
  verify the actual wire `tools/list`/`tools/call` using an MCP client. Also check
  the supported HTTP path if included in the intended release target.
- [x] Record versions, commands, dated outcomes, failed attempts and relevant
  traces. Retain only public financial inputs; no private client database is needed.
- [x] Offer a manual check: find Bitcoin, find and compare deposit/equity indexes,
  construct a bounded frontier, and submit a small multi-stage plan using only
  the MCP descriptions and schemas. Correct behavior includes useful correction
  of a deliberately misrouted rate and no guessed nested field names.
- [ ] With the reporter's model/client details, run matching before/after tasks
  and compare completion, invalid calls and tool-call count. Label this empirical
  result separately from passing deterministic tests; do not promise a fixed
  improvement percentage or universal success across models.
- [x] Prepare the change summary and compatibility notes.
- Release execution is authorized and tracked in epic #9: use `release-okama-mcp`,
  synchronize README/landing, and verify the published version. A green local
  suite is not delivery.

## Execution notes

The CI-equivalent development gate uses the exact public Planner source pinned
in `.github/workflows/ci.yml`; the earlier blanket stop on #6 was corrected.
The core implementation and bounded live/wire tests are complete locally.
Independent Grok4.6 review completed without material findings after the
earlier bounded attempts. See the combined validation receipt.
Restrictive frontier bounds remain affected by upstream okama#132; only explicit
0–1 bounds are claimed by the successful wire check. Upstream findings #131,
#132 and #133 are filed and linked. Reporter-specific replay requires model/client details. Publication status and
exact delivery receipts are maintained in epic #9.

## Definition of done

All affected public specs are discoverable and callable, nominal returns work
without inflation, exact Bitcoin discovery succeeds in the fixed fixture, all
filtered rows can be paged, oldest-history behavior is preserved, and wrong
macro inputs produce useful guidance. Offline tests, bounded live checks and
ruff pass with receipts. Model-level results and publication status are reported
separately; missing reporter details do not block deterministic engineering work.

## Planning validation

The author checked file references, task dependencies, interface consistency and
coverage against the design. `git diff --check` and `poetry run ruff check .`
passed; tests were not run because this planning change adds documentation only.
An independent Grok review was admitted with fresh 65% subscription usage and a
120-second deadline. It read six files but timed out without delivering findings;
this is not an independent-review pass. The owned review process exited, and
its partial log is retained under `tmp/plan-review.jsonl`. That planning attempt was not a pass; the later implementation review completed
without material findings, as recorded in the combined validation receipt.
