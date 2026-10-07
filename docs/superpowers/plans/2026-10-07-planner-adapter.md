# okama Planner adapter — RS-701

## Approved scope

Add a thin, stateless planner_forecast tool to the existing okama-mcp server. Accept the
complete ForecastRequest from the separately installed okama Planner library and return its
versioned household result. Reuse its actual Pydantic schema, without copying financial logic.
Existing finplan tools keep their inputs and outputs. Production HTTP deployment is excluded.

The Planner release is not published or licensed yet. Enable this optional tool when the
companion package is installed; the existing server must still start without it. Local acceptance
uses the reviewed wheel from RS-700. No local path or private-repository dependency is committed.
Installation of a public companion release will be documented when RS-702 provides it.

## Steps and evidence

- [x] RED: registered input schema is the real complete household schema.
- [x] RED: actual MCP calls preserve baseline/deferred results, validation, no network.
- [x] Implement optional schema loading and thin delegation/error translation.
- [x] Verify absence of companion package leaves existing tools available.
- [x] Exercise real local stdio client and save both synthetic results.
- [x] Document connection configuration, request and manual checks.
- [x] Full test suite, Ruff and independent review; reconcile RS-701 and epic.

Only the adapter worktree is edited. No new server, CLI, database, chart engine or financial
formulas. Goal-specific investing/gamma are not advertised. No production hosts are mutated.

Acceptance: 287 passed, 26 deselected; Ruff clean on FastMCP 4.0.11. Five targeted adapter
checks also pass on 2.7.0 with Pydantic 2.11.7/settings 2.9.1. Both real stdio examples reproduce
saved results on 4.0.11. A pre-existing full-server registration failure on 2.7.0 is documented
in docs/planner.md and RS-701; its baseline control reproduces without Planner. Independent
review passed. Public companion publication remains RS-702; production deployment is excluded.
