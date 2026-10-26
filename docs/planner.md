# Planner client data modes

MCP uses Planner's public Python APIs for all database operations. Client tools
never execute SQL, inspect schema or implement their own deletion cascade.

## Installation

Prepared MCP 3.1.0 requires `okama-planner[reports]>=0.5.0,<0.6.0`.
Local client tools require `okama_planner.ai.PlannerClientAccess` from Planner 0.5.0
source. PyPI currently provides 0.4.1, which lacks the AI facade. A source checkout
uses an immutable public revision in `tool.uv.sources`, also used by CI:

```bash
uv sync --all-groups
```

For a pip-managed environment, install this checkout and the compatible companion:

```bash
python -m pip install -e . 'okama-planner[reports] @ git+https://github.com/mbk-dev/okama-planner.git@c69d86ec731cbd09b1f708589d768c6f1cab2857'
```

Missing companion APIs fail closed; no raw-storage fallback is used. Market tools
keep their existing contracts. Older databases must be migrated using Planner's
own migration procedure before opening them with the new companion.

## Local setup

Select an existing database and report directory explicitly:

```bash
uv run okama-mcp stdio \
  --client-db /absolute/local-data/clients.sqlite3 \
  --reports-dir /absolute/local-reports
```

Only stdio supports these options. HTTP exposes neither client tools nor local
reports. Tool arguments cannot select a database or output directory. The retired
`install-skill` intake command remains unavailable. The legacy `--allow-personal-data`
flag initializes personal access only when no saved mode exists. A mode saved
through MCP always takes precedence, including an explicit revocation.

## Switch through MCP

| Call | Effect |
|---|---|
| `client_data_mode_get({})` | Return `{"mode":"anonymous"}` or `{"mode":"personal_data"}` |
| `client_data_mode_set({"mode":"personal_data"})` | Enable full client reads and persistent writes |
| `client_data_mode_set({"mode":"anonymous"})` | Restore pseudonymous reads and reject all client writes |

A database without a saved setting uses `anonymous`. In this mode, update personal
data in the Planner application. Financial calculations on anonymous inputs remain
available. All client writes, including metadata, residency and plan saves, require
`personal_data`. This intentionally replaces the earlier safe-metadata write behavior.

The mode persists across server restarts and connections to the same canonical
database path. The owner-only `<database>.mcp-access.json` sidecar stores only the
mode, outside Planner's schema. Back it up with the database if the policy should
travel with the database. A database moved without its sidecar defaults to anonymous.
The directory must be writable to change the setting. A malformed or unreadable
sidecar blocks client access; a successful mode-set call can replace it. No personal
values or database paths appear in mode responses.

Each operation reads the current setting. An operation already in progress can
finish after a switch; subsequent operations use the new mode. Concurrent switches
use the last successfully replaced setting. This is an explicit workflow setting,
not authentication: a caller authorized to use these local tools can change it.
Turning anonymous mode back on does not erase data already returned to a client.

## Client tools

| Tool | Inputs | Anonymous mode | Personal data mode |
|---|---|---|---|
| `client_get` | `code` | Pseudonyms | Full client record |
| `client_list` | None | Pseudonyms | Full client records |
| `client_create` | `details`, including `full_name` | Rejected | Create a record |
| `client_update` | `code`, sparse `changes` | Rejected | Update supplied fields |
| `client_delete` | `code` | Rejected | Delete client and linked Planner records |
| `client_set_tax_residency` | `code`, `residency={year,country,note?}` | Rejected | Save residence and optional note |
| `client_get_tax_residency` | `code`, `year` | Pseudonymous note | Full residence record or null |
| `client_save_plan` | `code`, full `request` | Rejected | Save version; return `{code,version}` |
| `client_load_plan` | `code`, `version` | Coded labels | Original saved request |
| `client_list_plans` | `code` | `{code,version}` entries | Same |
| `client_forecast` | `code`, `version` | Anonymous signed forecast | Same |
| `client_meeting_list` | `code` | Masked meeting text | Full meetings |
| `client_meeting_save` | `code`, `meeting`, optional `meeting_id`, `revision` | Rejected | Save meeting; edits require current revision |
| `client_meeting_delete` | `code`, `meeting_id`, `revision` | Rejected | Delete meeting with current revision |
| `client_history` | `code`, `table`, optional `offset`, `limit` | Rejected | Read owned history; at most 500 rows per page |

Creation/updates support name, CRM ID, sex, birth year, contacts, broker names,
primary contact channel, investment declaration date and notes. Unknown/system
fields are rejected. Omitted update fields remain unchanged; explicit null clears
optional values when the merged record passes Planner validation. Creation is not
idempotent; inspect the registry before retrying an ambiguous result. Deletion
uses Planner's transaction, removes linked database history and preserves unrelated
clients; it does not delete external documents or report files.

## Forecasts, reports and errors

`planner_forecast`, `planner_compare_modes` and `client_forecast` always use
Planner's anonymous calculation facade, regardless of client data mode. Identifying
free-text labels become pseudonyms; numeric financial inputs remain unchanged.

`planner_export_report` requires a signed safe forecast and rejects unsigned or
tampered results. After a server restart, obtain a new forecast before exporting.
The output contains only an opaque artifact basename, language and scenario count.
Reports stay anonymous in both modes. The legacy startup brand option remains
ignored; use Planner for personalized deliverables.

Validation and runtime errors use fixed translated messages (`en`, `ru`, `de`,
`es`, `zh`) without caller values, paths, chained causes or database details.
Access-denied errors identify the mode switch needed to enable personal operations.

## Synthetic hands-on check

```bash
uv run python examples/local_planner_client.py
```

This starts real stdio processes against a new synthetic database under `tmp/`.
It verifies default masking and blocked writes; switching on; full CRUD, residency
and plan saves; persistence in a restarted process; switching off; anonymous
forecasts and reports. It never opens a real client database.

For an interactive check, connect with the command above against a synthetic DB:
read the mode, try a write while anonymous, switch to personal_data, create/edit/read
a synthetic client, reconnect and verify the saved mode, then switch to anonymous
and verify pseudonyms and blocked deletion. Enable personal_data before deleting
the synthetic client; its other records are removed with it.


## Canonical database and release gates

Use the same Planner-owned database for the HTML interface, MCP and older LFP
commands. Migrate/import with Planner's verified procedures and retain backups;
never run old LFP migrations against the canonical database. See Planner's
[one database guide](https://github.com/mbk-dev/okama-planner/blob/main/docs/unified-database.md).

CI tests the pinned development companion and an installed MCP wheel in an isolated
environment using `tests/release/published_pair.py`. This checks real stdio,
anonymous and personal modes, meetings, forecasts and report tamper rejection.
It does not prove PyPI availability. Tag-triggered release gates ignore development
sources (`--no-sources`), require published Planner and verify the published MCP
package after upload. These gates remain unchanged. No release is performed as
part of this change.
