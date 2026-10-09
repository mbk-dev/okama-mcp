# Planner and local client workflows (2.0.0)

Version 2.0.0 exposes Planner calculation, local client registration and
local Excel export through MCP. It delegates to the public MIT-licensed
[okama Planner](https://github.com/mbk-dev/okama-planner) API. Existing finplan and
portfolio contracts are preserved.

## Compatibility and installation

MCP 2.0.0 requires `okama-planner[reports]>=0.4.0,<0.5.0` as a runtime dependency.
An ordinary installation includes the Planner calculation/storage library and its
Excel dependencies; there is no separate companion installation step for end users.
Local database paths, report output directories and private presentation files
remain explicit server configuration, not package data.

[Planner v0.4.0](https://github.com/mbk-dev/okama-planner/releases/tag/v0.4.0)
contains the registry API, reports and forecast/comparison capabilities. Its released
wheel SHA-256 is `ceb72306dfc2b1b7b7faa01d87cc05093de3284f29c42a15ebb0bbf96965e68c`.
The old v0.3.0 wheel lacks storage and is not supported by this release.

**Dependency publication status (2026-10-09):** Planner 0.4.0 and okama 4.0.0
are available on PyPI. MCP requires `okama>=4.0.0`; both libraries require Python
>=3.11. Direct GitHub/path dependencies are not shipped in MCP package metadata.

Ordinary usage is:

```bash
uvx okama-mcp stdio
# or in a local Poetry project:
poetry add 'okama-mcp==2.0.0'
```

To verify the unpublished candidate, add only the built MCP wheel to a fresh local
Poetry project. Planner, its report libraries and okama resolve automatically from
PyPI:

```bash
poetry init --name local-planner --python '>=3.11,<3.12' --no-interaction
poetry add /absolute/path/to/okama_mcp-2.0.0-py3-none-any.whl
```

Run `examples/local_planner_client.py` with this environment's Python for synthetic
stdio acceptance. FastMCP >=4.0.11,<5 remains required.

## Configure a local installation

Create local directories yourself. Supply absolute paths; the server does not
search for databases, migrate files, or read private folders automatically.

```bash
poetry run okama-mcp init-client-db --path /absolute/local-data/clients.sqlite3
poetry run okama-mcp install-skill --destination /absolute/project/.agents/skills
poetry run okama-mcp stdio \
  --client-db /absolute/local-data/clients.sqlite3 \
  --reports-dir /absolute/local-reports \
  --report-brand /absolute/local-config/report-brand.json
```

Initialization exclusively creates a new owner-only empty database. It refuses
an existing file. Startup requires an existing database with Planner's validated
current schema. All client tools use that one configured path; MCP arguments
cannot select another database. POSIX locking is required for creation receipts.
The receipt directory beside the database must remain with it during backups.

A local MCP client uses the executable from `poetry env info --path`:

```json
{
  "mcpServers": {
    "okama-local": {
      "command": "/absolute/poetry-environment/bin/okama-mcp",
      "args": ["stdio", "--client-db", "/absolute/local-data/clients.sqlite3",
               "--reports-dir", "/absolute/local-reports"],
      "env": {"MPLBACKEND": "Agg"}
    }
  }
}
```

Only configure this in a trusted local client. The HTTP command accepts none of
these local options and its server factory starts with a separate public registry.
The public HTTP service has no client or local report tools. No database path is
read from environment variables. Local records are never uploaded by these tools.

The packaged skill installs into `.agents/skills/create-client/SKILL.md`; Codex can
discover it there in that project. For Claude Code, create the project's
`.claude/skills/create-client` adapter to the same installed directory. Install
refuses different existing content; review custom skills before upgrading them.

## Client tool contracts

| Tool | Inputs / result |
|---|---|
| `client_create` | `details`, persistent caller `request_id`, optional `allow_duplicate=false`; status plus client or candidates |
| `client_get` | `code`; complete registry record |
| `client_list` | No arguments; all records in the configured local registry |
| `client_update` | `code`, partial `changes`; validated complete updated record |
| `client_set_tax_residency` | `code`, `residency={year,country,note?}`; creates/updates that year |
| `client_get_tax_residency` | `code`, `year`; that row or null |

Discovery exposes Planner's own nested ClientDetails and ResidencyDetails models.
Only `full_name` is required. Optional fields: `sex`, `birth_year`, `email`, `phone`,
`telegram`, integer `telegram_id`, `whatsapp`, `max_messenger`, `brokers`,
`primary_channel`, `ips_sent_at` and `note`. Primary channel needs a populated
matching contact. System-generated `id`, `code`, `created_at` cannot be supplied
or updated. Unknown fields fail. `brokers=null`/absent means unknown, `[]` means
explicitly no brokers. Patch omission keeps a field; null clears an optional field.
Clearing a primary contact also requires clearing/changing its channel.

Codes such as `c-0001` remain stable after server restart. Residency uses an
explicit year and assigned ISO alpha-2 country code, normalized to uppercase.
Repeated writes update that year; earlier years are not inherited. Residence
storage does not implement jurisdictional tax calculations.

### Retries and possible duplicates

Reuse the same unique `request_id` and input after a lost response. A completed
receipt returns `status: replayed` and the same code, even if contacts changed
later. Reusing an ID with different inputs fails. Creation receipts store only an
input digest, state and code in owner-only files; back them up with the database.

Normalized full-name matches return `status: duplicate` and candidates without a
write. The skill also examines existing contacts/spellings before creation. Select
an existing person's code, or explicitly confirm a different namesake before
setting `allow_duplicate=true`. A duplicate response has no saved receipt, so that
confirmed call can reuse the original ID.

Concurrent MCP creators are serialized with a file lock. Direct Planner API
writers do not participate in that duplicate/receipt guard. If a process ends
between receipt preparation and completion, the next call fails with a pending
receipt rather than creating again. Inspect `client_list`/`client_get` and stop
creation until an operator resolves it; do not generate a new ID as a retry.
Database and receipt files must not be edited by agents to bypass this safeguard.

## Planning and local reports

`planner_forecast(request)` accepts the complete companion ForecastRequest.
`planner_compare_modes(baseline, variant)` shares household inputs, aligned joint
monthly returns, seed and simulation count, comparing single/per-goal allocation.
Use `examples/planner/*-request.json`. Inputs are independent; baseline/variant
calls do not set implicit scenario state. Frozen samples make examples offline;
holdings-based history requires market data.

Supported: household budgets, fixed-payment loans, reserves/savings, non-working
assets, dated goals, retirement spending, pooled or explicitly allocated goal
portfolios, full-plan and goal funding metrics, ledger, portfolio/net-capital
series and provenance. Fixed-rate savings differ from investment goal portfolios.
Gamma/equivalent alpha, FX conversion, transaction fees and jurisdictional taxes
are not supplied. Planner financial-version/scenario/run persistence and chart
rendering remain companion Python APIs, outside this release's MCP registry tools.

`planner_export_report(report)` is local only. `report` contains one/two `scenarios`
(each `label`, complete `request`, saved `result`), a new `.xlsx` basename `filename`,
and `language` (`en`, `ru`, `zh`, `de`, `es`; default en). Planner verifies provenance
and matching horizons; export never recalculates the forecast. Path traversal and
overwrite are refused. Reports require the companion reports extra (`openpyxl`,
`pillow`). Server-side report branding uses a private JSON file, for example:

```json
{"company": "Synthetic Practice", "contact": "fiction@example.invalid", "color": "244C66"}
```

Optional `logo` is a local path, relative to that brand file or absolute. This is
Planner's ReportBrand interface; arbitrary branded Excel templates are not consumed.
Keep organization templates separately and adapt them locally to supported Planner
presentation/report interfaces. No private template or logo is shipped here.

## Synthetic acceptance and hands-on checks

`poetry run python examples/local_planner_client.py` creates a fresh isolated run
under `tmp/local-planner-demo/`, installs the packaged skill, starts two separate
stdio server processes, and verifies creation, unknown-field rejection, [] brokers,
duplicate refusal, update, residency, retry/persistence, forecast, local branded
Excel export and absence of local tools in an unconfigured server. It saves MCP
schemas and the workbook there and closes each server subprocess.

The demonstration follows create-client's persistence/verification steps. For
missing-field behavior, try this synthetic prompt with the installed skill:
“Register Synthetic Person; no brokers; tax residency DE in 2026.” Expect one
grouped question for sex/birth year/contacts/channel/note. Answer unknown/skip;
`brokers` must remain [] and optional contacts remain null. The missing questions
are agent instructions, not required database fields. The automated suite exercises MCP persistence. A separate fresh-agent smoke check
verified the grouped question and proposed calls, then the clean-wheel MCP harness
persisted and read back those inputs. Native client discovery/wording can also be
checked hands-on with the prompt above.

Try an unsupported registry field: the call must fail without adding a record.
Repeat creation with the same ID: the code and registry count must stay unchanged.
Restart the server: the saved contacts/residence must survive. Repeat with another
ID and same name: inspect candidates before deciding. The mode example has single
funding=1 and per_goal funding=0 because the latter's purchase portfolio is empty.
A changed comparison seed must fail. Check portfolio/net-capital series separately.
For observed versions and artifact evidence, see [release notes](releases/2.0.0.md).

## Upgrade and private installations

Upgrade the MCP server; its dependency declaration installs compatible Planner
and report libraries automatically. Adjust the local MCP
executable/configuration, install/review the skill, and retain local records,
receipts and presentation files outside the public repository. Existing portfolio
inputs remain valid. FastMCP 2.x is no longer a supported environment for 2.0.0.

There is no live LFP database migration in this release. Do not point Planner at
an unrecognized private schema. A separately reviewed migration must map supported
fields through Planner APIs, preserve identity/residence, reconcile unknown/empty
brokers and duplicate contacts, and verify synthetic backups/replay before touching
real records. Planner's `upgrade_database` handles only its recognized revisions,
not an arbitrary private database. No live installation was replaced for acceptance.
