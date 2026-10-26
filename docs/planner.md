# Planner client access and one local database

MCP 3.1.0 requires `okama-planner[reports]>=0.5.0,<0.6.0`. Planner owns database
access, migrations, identities, planning history, CRM and meetings. MCP imports no
SQLite/SQLAlchemy layer and executes no SQL.

## Default: anonymous read-only client access

```bash
okama-mcp stdio --client-db /private/planner/clients.sqlite3 --reports-dir /private/reports
```

The database and report directory must already exist. Client names, contacts and
free-text labels are pseudonymized inside Planner. No persistent client mutation
tools are registered. Client maintenance happens in Planner's local HTML interface.
There are 52 public tools, or 60 with anonymous local client access and report export.

## Explicit local opt-in: personal reads and mutations

```bash
okama-mcp stdio --client-db /private/planner/clients.sqlite3 --reports-dir /private/reports --allow-personal-data
```

This enables full client records, including names, contacts and CRM identifiers,
and client creation/update/deletion, meeting CRUD and bounded history pages (68 tools
with report export). All operations call `okama_planner.ai.PlannerClientAccess`.
Planner validates records, selects ownership, commits/rolls back writes and rejects
stale meeting revisions. Client deletion removes owned history; references from a
different client make it fail atomically. Historical tables are read using
`client_history(code, table, offset, limit)` with at most 500 records per page.

The flag is accepted only at local stdio startup with an explicit database. It is
not a tool parameter and cannot be enabled by an LLM. Restart without the flag to
revoke personal access. Public HTTP never enables local client/report tools.

## One canonical database

Use the same Planner-owned SQLite file for the HTML interface, MCP and older LFP
commands. Import previous advisory history using Planner's verified importer; keep
backups and retire the old working file after complete readback. Do not run old
LFP migrations on the canonical database. See Planner's
[one database guide](https://github.com/mbk-dev/okama-planner/blob/main/docs/unified-database.md).

## Forecasts, reports and failures

Forecast tools remain stateless and anonymous; reports require untampered signed
results from the current MCP process. Unsigned/tampered results fail without leaving
a workbook. Exports use neutral local branding and return only an artifact basename.
Personal access does not disable report proofs or sanitized error messages.

## Verification

Before publication, development setup and CI use the immutable Planner source pin
in `tool.uv.sources`. uv builds and installs the companion package. CI runs the full
default suite, then installs the MCP wheel with the exported runtime dependencies
in an isolated environment and runs real stdio acceptance. This proves development
compatibility, not availability from PyPI.

The tag-triggered release gate ignores development sources with
`uv sync --all-groups --no-sources`, tests the suite and installs the MCP wheel using
only published dependencies. It verifies the exact MCP package from PyPI after upload.
Until Planner 0.5.0 is published, that gate must fail; no release was performed on
26 October 2026. Remove the development pin after published-pair acceptance passes.
`tests/release/published_pair.py` checks default read-only anonymization, explicit
personal CRUD, forecast/comparison, storage, reports and rejected invalid proofs.
The installed-wheel gates use Python `-I`, check imports inside the environment,
and do not inject a companion checkout through `PYTHONPATH` or an editable install.
