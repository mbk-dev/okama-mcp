# Local household planning with okama Planner

The optional `planner_forecast` tool delegates to the separately installed **okama Planner**
companion library. It adds household budgets, fixed-payment loans, savings/reserve accounts,
non-working assets and dated goals to an investment forecast. The existing `finplan_forecast`,
`finplan_backtest` and `plot_finplan_forecast` tools continue to accept their existing portfolio-
stage specifications. Their contracts have not changed.

Only the single investment-portfolio mode is available. Separate fixed-rate savings accounts
are not investment portfolios per goal. Gamma/equivalent alpha, jurisdictional tax models,
FX conversion, white label reports and Planner charts rendered as images are not supplied here.
Planner returns numeric series for separate portfolio and net-capital charts. The existing
portfolio chart tool is not a household/net-capital report renderer.

## Install the public companion

[okama Planner v0.1.0](https://github.com/mbk-dev/okama-planner/releases/tag/v0.1.0)
is available under the MIT license. The MCP adapter does not declare a hard dependency on
the optional companion or on a private application. Existing
installations remain usable without the companion; the Planner tool is registered only when
`okama-planner` is importable. There is no `planner` installation extra.

From the adapter source checkout:

```bash
poetry env use python3.11
poetry install
poetry add "https://github.com/mbk-dev/okama-planner/releases/download/v0.1.0/okama_planner-0.1.0-py3-none-any.whl"
poetry run python examples/planner/client.py
```

The `poetry add` command modifies your local dependency declaration. Install the companion into
the same environment as the MCP server. The adapter is available on `main`; existing indexed
server packages and the public HTTP server have not been updated for this integration.
No private registry, client database or spreadsheet template is read.
The demonstration uses entirely synthetic return histories and does not fetch market data.

## Connect a local MCP client

Run from that environment:

```bash
poetry run okama-mcp stdio
```

A client configuration can point directly to its installed executable:

```json
{
  "mcpServers": {
    "okama-with-planner": {
      "command": "/absolute/path/to/checkout/.venv/bin/okama-mcp",
      "args": ["stdio"],
      "env": {"MPLBACKEND": "Agg"}
    }
  }
}
```

The executable path must match `poetry env info --path`; environments are not always in `.venv`.
This configuration is local. It does not deploy or alter the public HTTP server.

Call `planner_forecast` with `{"request": <complete request>}`. Use
`examples/planner/baseline-request.json` as the request value, then
`examples/planner/deferred-request.json` for a second independent call. MCP discovery exposes
the complete nested request schema directly from the companion's Pydantic model; no copied
financial validation or schema is maintained in the adapter. Unknown fields/invalid inputs are
reported as MCP tool errors. Every call supplies all inputs and has no implicit scenario state.

The second request changes only the purchase year, July 2028 to July 2029. Both use the same
synthetic monthly histories, 500 paths and seed 42. The purchase amount is indexed, so its
nominal price changes as well. The output retains `schema_version`, currency, single-portfolio
mode, ledger, portfolio flows, goals, forecast metrics, chart series and provenance. Each goal's
`p_affordable` and `p_alive` differs in meaning from full-plan `probability_of_success`.

## Ready results and verification

`examples/planner/*-result.json` are saved results from real calls to the local stdio server.
The example client writes newly calculated results and the advertised schema to
`tmp/planner-mcp-demo/`, then closes its server subprocess. Reproduction depends on frozen
inputs and all numerical-library versions, not just the seed. The saved provenance records
okama 3.0.0, numpy 2.4.6, pandas 3.0.6 and scipy 1.17.1; Python 3.11.15 and FastMCP 4.0.11
were used for this local acceptance.

The adapter's five targeted tests also pass on FastMCP 2.7.0 with Pydantic 2.11.7 and
pydantic-settings 2.9.1. That older FastMCP retains schema references and removes nested
`additionalProperties`; unknown fields are still rejected by the companion model at runtime.
Full-server stdio acceptance uses 4.0.11: the pre-adapter server already fails to register
`search_assets` on 2.7.0 (`NameError: Any` while resolving decorated-function annotations).
Installing 2.7.0 with Pydantic 2.13.5/settings 2.15.0 also fails during FastMCP import.
These are observed lower-version limits, not a tested full-server configuration.

Baseline: success 0.974; terminal portfolio median 25291.057126370935 USD.
Deferred: success 0.972; terminal portfolio median 25412.62632800031 USD.
These are synthetic Monte Carlo estimates, not market forecasts or proof that deferral is better.

For a manual test, verify that discovery includes `planner_forecast` and the existing finplan
names; both example requests work; the purchase month changes; portfolio and capital series
remain separate; invalid or unsupported request fields produce an error. Stop the client/server
after testing. `poetry run pytest -q` exercises MCP schema, repeated independent calls,
validation, no-network calculations and companion-absence behavior. Companion calculation
tests are skipped in an environment where the optional package is not installed.
