# okama-mcp: free & self-hosted distribution, MVP → v1.0

**Date:** 2026-06-04
**Status:** approved by user (brainstorming session)

## Background & decision

The original roadmap assumed a hosted remote MCP server at `mcp.okama.io` with
bearer-token auth (and, eventually, a subscription model). That direction is
**abandoned**. The new model:

- okama-mcp is **free, open source, no registration**.
- Supported usage: **local install** (stdio) or **self-hosting on the user's own
  server** (streamable-http behind the user's reverse proxy).
- The public `/mcp` endpoint at `mcp.okama.io` is **decommissioned**;
  `mcp.okama.io` remains as a landing page with install instructions.

Bearer-token auth is dropped from the roadmap entirely (it was never implemented).

## Scope

Four milestones, in order:

### M1 — Repositioning

1. **Decommission the public endpoint** on `secondvds`:
   - stop & disable the okama-mcp service;
   - remove the `location /mcp` block from the nginx vhost (on the server and in
     `deploy/nginx/okama-mcp.conf` in the repo);
   - keep the landing page; rewrite it: what okama-mcp is, install via
     `uvx okama-mcp`, link to GitHub.
2. **README rewrite**:
   - primary install path: `uvx` / `pipx` from PyPI (after M2 ships; until then
     git clone stays documented);
   - the "Remote (streamable HTTP)" section is reframed from "our hosted
     endpoint" to "self-hosting on your own server"; `deploy/` configs become a
     self-hosting example;
   - remove the bearer-token TODO line.
3. **Python floor → 3.11**:
   - `pyproject.toml`: `python = ">=3.11,<4.0.0"` — identical to okama's own
     constraint (verified: okama requires `>=3.11,<4.0.0`);
   - `.python-version` → 3.11 (dev environment on the minimum);
   - audit the code for syntax/APIs newer than 3.11 and fix;
   - per AGENTS.md rule: keep the floor aligned with okama's constraint whenever
     either changes.
4. **No code removal**: the `streamable-http` transport stays — it is the
   self-hosting mechanism.

### M2 — PyPI + CI/releases (v0.2.0)

1. Package name `okama-mcp` (check availability on PyPI at implementation time;
   fallback: `okama-mcp-server`).
2. GitHub Actions:
   - `ci.yml` — pytest (unit only, no `-m integration`) + `ruff check` on
     push/PR; Python matrix 3.11 / 3.12 / 3.13 / 3.14;
   - `release.yml` — on tag `v*`: build and publish to PyPI via Trusted
     Publishing.
3. Live-integration tests (hit `api.okama.io`) stay manual/local — not in CI.
4. **Post-release docs update:** once the package is live on PyPI, switch the README's
   primary install path to `uvx` / `pipx` (including the client config snippets) and
   update the mcp.okama.io landing page with the same instructions; redeploy the
   landing to secondvds.

### M3 — Graphics tools (v1.0.0)

Five new tools in `src/okama_mcp/tools/plots.py`, each returning a PNG chart as
MCP image content:

| Tool | Chart |
|---|---|
| `plot_wealth_index(portfolio)` | Portfolio wealth index (with assets / inflation) |
| `plot_drawdowns(portfolio)` | Drawdown series |
| `plot_monte_carlo(portfolio, mc, cashflow)` | MC forecast fan with percentiles |
| `plot_efficient_frontier(frontier)` | EF curve (with asset points) |
| `plot_assets(symbols, ccy, ...)` | Wealth-index comparison of individual assets |

Design constraints:

- Inputs reuse the **existing** pydantic specs (`PortfolioSpec`, `FrontierSpec`,
  `MCSpec`, `CashflowSpec`); okama objects come from the existing content-hash
  cache.
- Rendering: matplotlib (`MPLBACKEND=Agg`, already a project rule) → PNG into
  `BytesIO` → `fastmcp.utilities.types.Image(data=..., format="png")` (FastMCP
  converts to MCP `ImageContent` automatically — confirmed in FastMCP docs).
- Where okama has built-in plot methods, use them; otherwise build the figure
  from okama data with matplotlib. The exact tool → okama-method mapping is
  fixed in the implementation plan.
- **Thread-safety check (to resolve in the plan):** pyplot holds global state
  and is not thread-safe — either use the OO API (`Figure` without pyplot) or
  guard rendering with a lock, depending on how okama builds its own plots.
- Fixed render defaults: `figsize=(10, 6)` inches at `dpi=150` → 1500×900 px PNG.
  Rationale: matplotlib's defaults (6.4×4.8 in @ 100 dpi = 640×480 px) were confirmed
  too small in manual testing on 2026-06-04; okama's own plot methods default
  `figsize=None` and inherit those rcParams. No size parameters on the tools (YAGNI).
- Existing data tools are **not** modified; tool count grows ~16 → ~21.
- TDD: unit tests assert a valid PNG (magic bytes, non-zero size) on mocks;
  live rendering covered in the integration suite.

### M4 — Tool expansion + catalog listing

1. Candidate new tools (direction only; each candidate is **verified against
   the real okama API during planning** — anything unconfirmed is dropped):
   - rolling metrics (windowed CAGR / risk),
   - dividend yield,
   - inverse percentile / probability metrics for a portfolio.
2. After the first PyPI release: register in the official MCP registry and
   relevant catalogs (procedure and current catalog list verified at
   implementation time, not from memory).

## Out of scope

- Hosted/remote MCP service of any kind, auth, registration, billing.
- Docker image (PyPI via uvx/pipx is the only distribution channel for now).
- Plotly JSON output from tools (PNG only).
- Reuse of the future okama-web Analytics REST API — that spike belongs to the
  okama-web backend spec, not to this roadmap.

## Error handling & testing

- Graphics tools reuse the existing `errors.py` translation of okama exceptions
  to actionable MCP errors.
- TDD per AGENTS.md for every production-code change; `poetry run pytest -q`
  and `poetry run ruff check .` gates apply.
