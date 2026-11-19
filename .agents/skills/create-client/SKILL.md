---
name: create-client
description: Use when registering a Planner client or choosing the intake path under the configured MCP client-data access mode.
---

# Register a Planner client

Read `client_data_mode_get({})` before choosing an intake path. The saved mode
applies to the configured database across connections and server restarts;
reconnecting does not reset it. Follow an explicit user request to switch with
`client_data_mode_set({"mode":"personal_data"})` for personal access or
`client_data_mode_set({"mode":"anonymous"})` for anonymous access.
Do not enable personal access merely to bypass a rejected operation.

## Anonymous mode

Keep identity intake in the Planner application. Ask only for the resulting
anonymous code, such as `c-0001`, and use `client_get` to verify its pseudonymous
record. Do not request or inspect personal intake fields or files through MCP.
All client writes are blocked, including metadata, residency and plan saves.
Existing coded plans can still be loaded and forecast.

## Personal data mode

For requested registration, use `client_create({"details":{...}})` with the
user-provided fields and the tool's current input schema; `full_name` is required.
Return the resulting client code. Full reads, sparse edits and deletion are
available within the requested task. An already selected personal mode survives
reconnection; it does not require a new opt-in for every call. Leave the saved
mode in place unless the user asks to change it.

`client_create` is non-idempotent. Treat a timeout or other uncertain outcome as
pending. Use permitted registry reads to reconcile it and return the client code
if you can confirm the record created by the original call. Retry only after
verifying that the original call finished without creating a record. A lookup
with no match leaves the outcome unresolved. Tell the user when registration is
still pending.

Omitted update fields stay unchanged. Explicit null clears an optional field
when Planner validation permits it. Forecasts and reports remain anonymous in
either mode.

If mode/client tools are unavailable or the mode cannot be read, use the Planner
application intake path. Local MCP access requires stdio with an explicitly
configured database and a compatible Planner API. Use the
[Planner integration guide](../../../docs/planner.md) for setup and contracts;
do not bypass it with raw storage APIs or direct database inspection. The packaged
skill installer remains retired.

This replaces the earlier human-only MCP intake restriction, following the
[persistent-mode decision](../../../docs/superpowers/specs/2026-10-26-client-data-modes-design.md)
implemented in [PR #18](https://github.com/mbk-dev/okama-mcp/pull/18) on 2026-10-26.
