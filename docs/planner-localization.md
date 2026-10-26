# Safe Planner language contract

Planner and local client-code tools support `en`, `ru`, `de`, `es` and `zh`.
Selection is explicit per call. Startup `--language` changes descriptions and
schema captions; omitted call language remains English. Market tools retain their
existing contracts.

`planner_export_report` uses `report.language`. Other Planner/client tools accept
an optional top-level `language`. Invalid language values receive a fixed English
error without echoing the submitted value.

In anonymous mode, English client reads return pseudonymous records. Other languages add
`presentation` rows containing `key`, translated `label` and safe displayed
`value`. The selected Planner facade record reaches presentation helpers: anonymous mode
never restores private values; personal_data mode presents the full client record.
Switching mode affects every language equally.
Dates and sex enum captions may be formatted for display; codes and machine keys
remain stable. Presentation does not write translated data to the database.

Mode descriptions and access-denied errors are translated in all five languages.
Errors use only a fixed caption. They never include submitted field names, values,
validation locations, exception causes or schema details. Validation and runtime
exceptions are sanitized before FastMCP's server logging. Missing privacy facade
fails closed, including when an older released companion is installed.

Run the synthetic language/error checks:

```bash
uv run pytest -q tests/test_planner_localization.py tests/test_ai_privacy_boundary.py
```

The legacy `--report-brand` argument is accepted for startup compatibility but ignored:
MCP never reads the identity/contact/logo file. Use Planner locally for branded human deliverables.
