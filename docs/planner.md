# Planner privacy boundary

Household and client tools require `okama_planner.ai`. A companion without this
facade cannot expose household tools; local client/report configuration fails closed.
An older installed Planner dependency must be upgraded to the privacy-capable release.
Market tools keep their existing contracts.

## Local setup

A human creates and populates the client database with Planner's local intake CLI.
Names and contacts must never be sent in MCP calls or AI prompts. The former
`client_create` tool is removed. `install-skill` refuses to install the retired AI
intake workflow, which is no longer included in packages.

Use explicitly selected local paths:

```bash
poetry run okama-mcp stdio \
  --client-db /absolute/local-data/clients.sqlite3 \
  --reports-dir /absolute/local-reports
```

Only stdio supports these options. The public HTTP server has no client tools or
local report tools. Tool arguments cannot select a database or output directory.
Planner owns all client and financial-plan database reads and writes. The MCP
adapter does not inspect tables, registry records or database schema.

## Client-code tools

| Tool | Inputs and safe result |
|---|---|
| `client_get` | `code`; pseudonymous client metadata |
| `client_list` | No required arguments; pseudonymous client metadata |
| `client_update` | `code`, `changes` containing only `sex`, `birth_year`, `ips_sent_at` |
| `client_set_tax_residency` | `code`, `residency={year,country}`; safe year/country record |
| `client_get_tax_residency` | `code`, `year`; safe record or null |
| `client_save_plan` | `code`, full `request`; `{code,version}` |
| `client_load_plan` | `code`, `version`; request with coded labels |
| `client_list_plans` | `code`; list of `{code,version}` |
| `client_forecast` | `code`, `version`; safe forecast with privacy proof |

Names, contacts, free-text notes and client-folder paths are absent from client
tool contracts. Unknown update fields and residency notes are rejected. Stable
codes survive restarts. Plan versions and computations are handled inside Planner.

## Forecasts and reports

`planner_forecast(request)` and `planner_compare_modes(baseline,variant)` delegate
exclusively to Planner's privacy facade. It replaces free-text labels with special
codes before calculation and removes identifying text from returned results.
Financial inputs and arithmetic retain their values. Full-plan and goal metrics,
ledger, portfolio/net-capital series and provenance remain available.

`planner_export_report(report)` accepts one/two scenarios containing `label`,
`request` and a signed safe `result`, plus a `.xlsx` basename `filename` and
optional `language`. Planner rejects unsigned or tampered results. Privacy proofs
belong to the current server process; after a restart, obtain a new safe forecast
before exporting. Export does not rerun forecasts. MCP generates an opaque artifact basename and returns `filename`,
`language` and scenario count without exposing the configured absolute directory.
The legacy startup brand argument is ignored and its file is never read by MCP. The local output is
not the personalized client deliverable; human-only rendering belongs in Planner.

Validation and runtime errors use fixed translated messages for all supported
languages, including English. Invalid languages fall back to English errors.
Neither field names supplied by the caller, private values, chained causes,
database schema nor filesystem paths appear in errors or server error logs.

## Synthetic hands-on check

```bash
poetry run python examples/local_planner_client.py
```

The example uses an isolated synthetic database under ignored `tmp/`, creates its
synthetic identity locally, starts separate stdio processes, and checks pseudonymous
reads, rejected contact updates, saved plan versions, residency, forecasts, reports
and restart persistence. No real database or private folder is opened.

For a configured MCP client, list tools and confirm `client_create` is absent.
Read a synthetic code in English and German: names and contacts must be absent in
both raw and presentation fields. Send an unknown update field containing a
synthetic personal marker, then an unsupported language containing that marker:
errors and server logs must not echo it. Export a signed forecast and confirm the
response contains only an artifact basename. Alter a forecast value or remove its
privacy proof: report export must fail without leaving a workbook.

CI checks the privacy contract against a pinned public Planner source commit until the
companion package is released. It also verifies that an older installed companion cannot
fall back to raw Planner tools. Production package requirements will advance with that release.
