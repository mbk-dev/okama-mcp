# Planner and local registry language contract

The household Planner tools and explicitly enabled local client tools support `en`, `ru`,
`de`, `es` and `zh`. Language selection is explicit and stateless; currency and previous calls
never select a language.

Start the server with `poetry run okama-mcp stdio --language ru` (or
`poetry run okama-mcp http --language ru`). This chooses descriptions and human captions in
these tools' input schemas. It does not change market tools, identifiers, enum values or the
underlying Planner models. `--client-db` and `--reports-dir` remain explicit local opt-ins
available only on stdio.

Every `planner_forecast`, `planner_compare_modes` and `client_*` call accepts optional
`language`, defaulting to `en` regardless of startup language. For example:

```json
{"code": "c-0001", "language": "de"}
```

`planner_export_report` uses the existing `report.language`, defaulting to `en`, for both the
workbook and errors. Report filename, scenario labels and saved financial data stay unchanged.
Forecast/comparison results always retain their existing raw machine-readable shape; language
controls errors and the startup schema help, rather than rewriting financial results.

English/default client calls retain their original output shapes. Other languages return:

- `client_get` and `client_update`: `{"client": <raw record>, "presentation": <rows>}`.
- `client_list`: `{"clients": <raw records>, "presentation": <rows for each record>}`.
- `client_create`: original `status` and `client`/`candidates`, plus `presentation` for each record.
- Residency tools: `{"residency": <raw record>, "presentation": <rows>}`; an unrecorded year stays `null`.

A presentation row contains `key`, translated `label` and displayed `value`. Full client names,
notes, broker names and raw enum/country codes are preserved. Dates and sex/contact-channel
captions are formatted separately. This presentation never writes translated data to SQLite.
Validation errors report field locations and translated messages without submitted values.
Unknown runtime errors receive a translated generic message rather than exposing private input.

The packaged MCP CSV supplies descriptions, registry captions and safe errors. If a companion
release provides shared `client_presentation`/`localized_error` helpers, the adapter uses them;
otherwise the published Planner dependency remains usable through the packaged fallback.
No unpublished dependency is required.

## Hands-on check

Use a synthetic database, with paths under this checkout's ignored `tmp/` directory:

```bash
mkdir -p tmp/language-check/reports
poetry run okama-mcp init-client-db --path "$PWD/tmp/language-check/clients.sqlite3"
poetry run okama-mcp stdio --language ru \
  --client-db "$PWD/tmp/language-check/clients.sqlite3" \
  --reports-dir "$PWD/tmp/language-check/reports"
```

Connect this command with an MCP client. List tools: Planner and client descriptions should be
Russian; registry field descriptions should be translated while keys and enums remain stable.
Create a synthetic client, then call `client_get` with `language: "de"`, `language: "zh"`, and
no `language`. The first two calls should contain raw `client` plus translated `presentation`;
the last should return the original raw record. Repeat the German call: it should be identical.
Send `planner_forecast` with `request: {}` and `language: "es"`: the response should contain
Spanish required-field errors without input values. Export a saved synthetic request/result
using `report.language: "ru"`: workbook captions should be Russian. A filename containing
`../` should be rejected in that report language without creating a file.

Automated synthetic checks:

```bash
poetry run pytest -q tests/test_planner_localization.py
poetry run pytest -q
poetry run ruff check .
```
