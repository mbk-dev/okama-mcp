# okama-mcp

MCP (Model Context Protocol) server that exposes the [okama](https://github.com/mbk-dev/okama)
investment portfolio toolkit to AI assistants — Claude Desktop, Claude Code, Cursor, and any
other MCP-compatible client.

With okama-mcp installed, you can ask an AI things like:

> *"Backtest a portfolio of 30% gold and 70% real estate over the last 15 years."*
>
> *"Run a Monte Carlo retirement forecast on that portfolio, withdrawing $1,000/month
> indexed to inflation, over 25 years."*
>
> *"What's the tangency portfolio of SPY, BND, and GLD with a 3% risk-free rate?"*

…and the AI uses the MCP tools to call okama directly — no Python code needed.

Built on [FastMCP](https://github.com/jlowin/fastmcp). Single codebase, two transports:
`stdio` (for local clients) and `streamable-http` (for self-hosting).
okama-mcp is free and open source — no hosted service, no registration; you run it
yourself, locally or on your own server.

## Install

Requires Python ≥ 3.11 (same floor as okama itself).

```bash
git clone https://github.com/mbk-dev/okama-mcp
cd okama-mcp
poetry install
```

## Run

```bash
# stdio — for Claude Desktop, Claude Code, Cursor (local IPC)
poetry run okama-mcp stdio

# streamable HTTP — for self-hosting on your own server
poetry run okama-mcp http --host 127.0.0.1 --port 8765
```

## Connect a client

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "okama": {
      "command": "poetry",
      "args": ["run", "okama-mcp", "stdio"],
      "cwd": "/absolute/path/to/okama-mcp"
    }
  }
}
```

Restart Claude Desktop; the server appears in the tools menu.

### Claude Code

From the project root — registers the server for this project only (`claude` must be
launched from this directory to see it):

```bash
claude mcp add okama poetry run okama-mcp stdio
```

To make the server available in **every** project (user scope), register the absolute
path of the venv binary — `poetry run` would not work outside the project directory:

```bash
claude mcp add --scope user okama -- "$(poetry env info -p)/bin/okama-mcp" stdio
```

Or commit a `.claude/mcp.json` so the whole team picks it up:

```json
{
  "mcpServers": {
    "okama": {
      "command": "poetry",
      "args": ["run", "okama-mcp", "stdio"]
    }
  }
}
```

### Cursor

Open *Settings → MCP*, click *Add new MCP Server*, and use:

- Name: `okama`
- Type: `stdio`
- Command: `poetry run okama-mcp stdio`
- Working dir: this project's root

### Self-hosting (streamable HTTP)

Run okama-mcp on your own server and share it across your MCP clients:

```bash
poetry run okama-mcp http --host 127.0.0.1 --port 8765 --path /mcp
```

Then point your MCP client at `http://<your-server>:8765/mcp`. For a production
setup put nginx + TLS in front; ready-made examples live in `deploy/`:

- `deploy/systemd/okama-mcp.service` — systemd unit (hardened, runs as a dedicated user)
- `deploy/nginx/self-hosted.conf` — nginx vhost: TLS, SSE-friendly proxying of `/mcp`

The server is open by design — free to run, no registration. If your instance must
not be public, restrict access at the nginx level (allow-list, VPN, or HTTP basic auth).

## Tool catalog

All tools are **stateless** — pass the full portfolio specification with every call.
The server caches expensive okama objects (`Portfolio`, `EfficientFrontier`) by content
hash, so repeated calls on the same spec are fast.

### Search & metadata

| Tool | Purpose |
|---|---|
| `search_assets(query, namespace?)` | Free-text search across all okama symbols by name / ticker / ISIN. |
| `list_namespaces(kind="all"\|"assets"\|"macro")` | Show the available okama namespaces. |
| `get_asset_info(symbol)` | Metadata for one symbol — name, country, currency, type, date range. |

### Single asset & comparisons

| Tool | Purpose |
|---|---|
| `get_asset_history(symbol, kind, first_date?, last_date?)` | Time series for one asset. `kind` ∈ {`close_monthly`, `close_daily`, `adj_close`, `ror`, `dividends`}. |
| `compare_assets(symbols, ccy, first_date?, last_date?, inflation)` | Side-by-side statistics (`describe()` table: CAGR, risk, drawdowns by period). |
| `get_correlations(symbols, ccy, ...)` | Correlation matrix of monthly returns. |

### Portfolio backtest

| Tool | Purpose |
|---|---|
| `analyze_portfolio(portfolio)` | Headline metrics + full `describe()` for a `PortfolioSpec`. |
| `get_portfolio_drawdowns(portfolio)` | Drawdown time series + max drawdown / recovery period. |
| `get_portfolio_var_cvar(portfolio, time_frame=12, level=1)` | Historical Value at Risk and CVaR. |
| `get_portfolio_wealth_index(portfolio, full=False)` | Wealth-index series (cumulative growth of 1000). |

### Monte Carlo DCF

| Tool | Purpose |
|---|---|
| `monte_carlo_forecast(portfolio, mc, cashflow)` | Forward simulation with one of five cash-flow strategies (`indexation`, `percentage`, `time_series`, `vanguard`, `cut_if_drawdown`). Returns percentile wealth bands, terminal-wealth stats, and survival metrics. |

### Efficient Frontier

| Tool | Purpose |
|---|---|
| `build_efficient_frontier(frontier)` | Full EF point table (Risk / Mean return / CAGR + per-asset weights). |
| `get_tangency_portfolio(frontier, rf_return, rate_of_return)` | Max-Sharpe portfolio on the EF. |
| `get_min_variance_portfolio(frontier)` | Global Minimum Variance portfolio. |

### Macro

| Tool | Purpose |
|---|---|
| `get_inflation(currency, first_date?, last_date?, include_cumulative?)` | Inflation series for a currency (`USD`, `EUR`, `RUB`, …). |
| `get_central_bank_rate(country, first_date?, last_date?)` | Central-bank policy rate (`US`, `ECB`, `RUS`, …). |

## Spec shapes

The complex tools take typed dicts validated by pydantic. The full schemas live in
`src/okama_mcp/schemas.py`; here are the headline shapes:

```jsonc
// PortfolioSpec
{
  "assets":   ["GLD.US", "VNQ.US"],
  "weights":  [0.3, 0.7],            // optional, must sum to 1.0
  "ccy":      "USD",
  "first_date": "2010-01",
  "last_date":  "2024-12",
  "rebalancing_period": "year",       // month | quarter | half-year | year | none
  "inflation": true
}

// MCSpec
{
  "distribution":  "norm",            // norm | lognorm | t
  "period_years":  25,
  "scenarios":     500,                // ≤ 5000
  "percentiles":   [5, 50, 95],
  "random_seed":   42                  // optional, for reproducibility
}

// CashflowSpec — discriminated by `type`
{ "type": "indexation",       "initial_investment": 1000000, "frequency": "month", "amount": -1000, "indexation": "inflation" }
{ "type": "percentage",       "initial_investment": 1000000, "frequency": "year",  "percentage": -0.04 }
{ "type": "time_series",      "initial_investment": 100000,  "events":    { "2030-06": -50000 } }
{ "type": "vanguard",         "initial_investment": 1000000, "percentage": -0.04, "floor_ceiling": [-0.025, 0.05], "indexation": "inflation" }
{ "type": "cut_if_drawdown",  "initial_investment": 1000000, "frequency": "year",  "amount": -60000, "indexation": "inflation",
  "crash_threshold_reduction": [[0.2, 0.4], [0.5, 1.0]] }

// FrontierSpec
{
  "assets":   ["SPY.US", "BND.US", "GLD.US"],
  "ccy":      "USD",
  "bounds":   [[0.0, 0.7], [0.1, 1.0], [0.0, 0.3]],   // optional
  "n_points": 20,
  "rebalancing_period": "year",
  "inflation": false
}
```

## Development

The project follows TDD (see `AGENTS.md`). After every code change run:

```bash
poetry run pytest -q
poetry run ruff check .
```

To run the live-API integration test (hits `api.okama.io`):

```bash
poetry run pytest -m integration
```

## Project layout

```
src/okama_mcp/
├── server.py          # FastMCP instance + registration entry point
├── transport.py       # CLI: `okama-mcp stdio | http`
├── schemas.py         # PortfolioSpec, MCSpec, CashflowSpec, FrontierSpec
├── cache.py           # TTL+LRU cache keyed by sha256 of canonical spec
├── serialization.py   # pandas → JSON-safe with smart truncation
├── errors.py          # Translate okama exceptions to actionable MCP errors
└── tools/
    ├── search.py, asset.py, asset_list.py
    ├── portfolio.py, monte_carlo.py
    ├── frontier.py, macro.py
```

## License

Same as okama itself: MIT.
