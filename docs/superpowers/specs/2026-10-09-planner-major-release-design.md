# Planner and local client workflows for MCP 2.0.0

## Outcome and authorization
Prepare a tested release candidate for issue #4, without committing, pushing,
publishing or deploying. Use synthetic records exclusively. Existing portfolio
contracts remain available. Public forecast calls remain stateless.

## Companion compatibility
Per the owner's updated decision, Planner is included through a mandatory runtime
dependency: `okama-planner[reports]>=0.4.0,<0.5.0`. Planner 0.4.0 and okama
4.0.0 are published on PyPI. Require `okama>=4.0.0` and verify the published pair;
no source/Git/path dependency belongs in distributed metadata.
Raise the FastMCP floor to the verified 4.0.11 full-server version for this major.
Python remains >=3.11, aligned with okama. Never commit poetry.lock.

## Local boundary
`stdio --client-db /absolute/path` registers six client tools using PlannerStore:
`client_create`, `client_get`, `client_list`, `client_update`,
`client_set_tax_residency`, `client_get_tax_residency`. No environment path fallback.
Opening requires an existing validated database; `init-client-db --path` explicitly
initializes a new database. HTTP accepts neither registry nor report path options.
No MCP input can choose a database. Open/close PlannerStore per call.

Reuse Planner ClientDetails and ResidencyDetails schemas dynamically. Updates use
a partial dictionary and Planner validates the merged record. Unknown fields fail;
null brokers means unknown, [] means none. Codes survive process restarts.

## Creation retries and duplicates
Require a caller-generated request_id reused across retries. Serialize local MCP
creators with a POSIX file lock alongside the database. Store owner-only, atomic
write-ahead request receipts alongside it, keyed by a digest of request_id. A receipt
binds the validated input and explicit duplicate decision to its returned code.
Same ID with different input fails. Completed retries return that code, even after
contacts change. A pending receipt after interruption fails safely and directs the
agent to list/get records; it never repeats creation automatically.
Check existing normalized names before creating. Return candidates without writing
unless the caller explicitly confirms a namesake (`allow_duplicate=true`). This
protection covers MCP writers; direct Planner API writes do not participate in it.

## Local reports and skill distribution
`stdio --reports-dir /absolute/path [--report-brand /absolute/file.json]` enables
`planner_export_report`, delegating saved request/result pairs to Planner's exporter.
Accept only a basename ending .xlsx inside the configured existing directory;
refuse overwrite. Local brand settings support company/contact/color/logo as
Planner does; no arbitrary workbook-template ingestion is promised. Export is a
local feature, requiring Planner reports extra, and never enabled on HTTP.

Ship generic English create-client instructions in wheel/sdist. The canonical real
skill lives in .agents/skills/create-client; Claude and package source adapters
point to it. `install-skill --destination /project/.agents/skills` copies the packaged
skill, refusing different existing content. The skill groups missing questions,
uses local MCP only, retains request IDs, handles duplicates, and reads back saved
fields and residency. No private CLI is involved.

## Evidence and limitations
Test actual MCP schemas and writes, unknown/empty fields, duplicate/retry conflicts,
concurrent creation, interrupted receipts, restart persistence, and HTTP exclusion.
Build and inspect wheel/sdist, run a clean Poetry installation against the pinned
companion candidate, and execute synthetic stdio forecast/registry/report acceptance.
Planner financial history, chart rendering and live-database migration remain Python
companion workflows; document them explicitly. Update README, landing teaser,
upgrade guide and draft release notes. Publication stays pending authorization and
indexed dependency availability and okama verification, with issue DoD reflecting evidence rather than intent.
