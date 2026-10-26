# Client data access modes

## Intent
Expose two explicit client-data modes through local MCP calls. The default is
`anonymous`: reads expose only Planner pseudonyms and persistent client writes
are rejected. `personal_data` permits client creation, full reads, updates and
deletion through Planner's public Python API. Identity intake remains in the
Planner application unless the caller explicitly selects personal access.

## Approach
The user selected persistence across connections. Provide `client_data_mode_get`
and `client_data_mode_set(mode)` MCP tools. Store a mode-only JSON sidecar beside
the canonical configured database (`<database>.mcp-access.json`). The scope is
one database, shared by all local MCP processes using it. Read the file for each
operation; absence means anonymous, corrupt/unreadable content fails closed.
Atomic replacement with owner-only permissions prevents partially written policy.
An already-started operation may complete when another connection switches mode;
the next operation reads the new setting. Concurrent switches use last-write-wins.

Session-only and per-request selection were considered; the user explicitly
chose persistence, overriding the general stateless preference for this setting.
The mode is user-controlled behavior, not authentication or protection against a
malicious MCP caller. Only configured local stdio exposes these tools; HTTP
remains calculation-only. No arbitrary file path is accepted in a tool call.

Delegate to `okama_planner.ai.PlannerClientAccess`, introduced in Planner 0.5.0
source. No SQL, schema changes, deletion traversal or privacy filtering belongs
in MCP. Creation and updates use strict schemas in `okama_mcp.schemas`.
All client writes, including residency and saved plans, require personal mode.
Deletion removes the client's linked Planner records atomically according to the
Planner API; it does not remove external documents. Forecast/report outputs keep
the existing anonymous signed contract in either mode. Missing companion support
fails closed. No actual client database is used during development.

## Acceptance
- Missing or explicit anonymous mode never returns synthetic identifying values.
- Anonymous CRUD writes, tax writes and plan writes fail without database changes.
- Explicit personal mode supports full CRUD, residency notes and saved plan labels.
- Switching persists across restarts and existing connections to the same database;
  other databases remain anonymous. Switching back revokes later personal operations.
- Invalid modes/fields and Planner failures do not leak values or paths into errors/logs.
- Deletion removes only the selected client's linked records; other clients survive.
- English/Russian/German/Spanish/Chinese help and errors describe the mode behavior.
- Run the full MCP suite with the pinned supported Planner source and Ruff;
  verify a real stdio subprocess using synthetic data.

## Dependency and delivery
Upstream main now requires Planner >=0.5.0,<0.6.0 and prepares MCP 3.1.0.
Preserve that dependency floor, the development source pin and all published-pair
release gates. Keep upstream meeting/history tools under the persisted mode.
The legacy startup opt-in only bootstraps an absent setting; a saved mode wins.
The user authorized commit and merge into main, explicitly excluding a release.
