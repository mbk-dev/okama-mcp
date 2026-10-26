# Client data modes implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan with TDD.

**Goal:** Add explicit anonymous/personal client access through MCP.
**Architecture:** Database-scoped persistent mode, default anonymous; all storage delegated to PlannerClientAccess.
**Tech Stack:** Python >=3.11, FastMCP 4, Pydantic 2, Planner 0.5 source.
**Spec:** ../specs/2026-10-26-client-data-modes-design.md

## Global constraints
Use the existing task worktree, synthetic data under tmp/, English documentation,
no production records or release publication. Commit and main delivery are authorized. Keep market tools and public HTTP unchanged.

## Review focus
Invalid/null modes must fail closed; omitted fields must not clear stored contacts;
explicit null updates must follow Planner validation; deletion must retain unrelated
clients; mode switches must persist across connections but not affect another database.

## Task 1: Client mode contract and API adapter
- [x] Write failing real MCP tests in tests/test_client_data_modes.py for both modes,
  full CRUD, sparse updates, tax notes, plans, deletion isolation and sanitized errors.
- [x] Run the new tests with pinned Planner source; retain expected RED evidence.
- [x] Add strict schemas, mode routing and safe localized errors; update existing
  tests for intentionally removed anonymous writes and expanded tool discovery.
- [x] Run targeted tests and verify GREEN.

## Task 2: Installation, help and verification
- [x] Preserve upstream Planner >=0.5.0,<0.6.0 in both dependency files and the
  c69d86ec731cbd09b1f708589d768c6f1cab2857 development source pin; document installation.
- [x] Update README, docs/planner.md, localization and synthetic stdio example.
- [x] Run uv run pytest -q with pinned source, uv run ruff check ., and real stdio smoke.
- [x] Review the final diff, resolve material findings and check Git locks.
  Independent final review was attempted but produced no verdict; see ledger.

## Ledger
User decision: persist mode across connections. The final design uses a database-scoped mode sidecar.
Baseline: 374 passed, 35 deselected. Initial RED: 19 new mode tests failed as expected.
API review: Grok grok-4.6-build session 01a17845-e50f-7323-a761-6edb2c83940c.
The startup-only policy in the upstream docstring is superseded at the MCP adapter
by the user request; Planner instances remain immutable. No Planner source change.

Task 1: complete. Targeted client/privacy/localization/transport tests: 58 passed.
Task 2 validation: uv run pytest -q -> 396 passed, 35 deselected; Ruff PASS;
real stdio example PASS (66 tools, three fresh processes). Local resource footprint
under 1 GB. No index/worktree lock; pre-existing shared checkout guard preserved.

Final review: external Grok review session 01a17851-2094-7c83-a296-b701f673c951
timed out after 180 seconds and a bounded 90-second continuation on the same model.
No final verdict; not accepted as a successful review. Read-only tool calls verified.
Author review found omitted residency note deletion: regression reproduced RED;
minimal adapter fix preserves omission and accepts explicit null. Final suite: 397 passed,
35 deselected; Ruff PASS; repeated real stdio smoke PASS (three processes).


Delivery integration: main advanced to 33d4b8e with Planner >=0.5.0, meeting/history
APIs, a development source pin and installed-wheel/release gates. Preserve these;
replace startup-only mode selection with persistent MCP selection. The legacy flag
bootstraps only an absent setting. Integration regressions: 3 expected RED failures.

Integrated validation: 402 passed, 35 deselected; Ruff PASS; installed-wheel
real-stdio acceptance PASS with 52 public / 70 configured local tools.
Release workflows and version remain unchanged from upstream main.
