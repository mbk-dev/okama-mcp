# Contributing to okama-mcp

Thanks for your interest in improving okama-mcp! This document describes how to set up a
development environment, the project's conventions, and what we expect from pull requests.

## Scope: okama-mcp vs okama

okama-mcp is a thin MCP wrapper around the [okama](https://github.com/mbk-dev/okama)
library. Keep that boundary in mind when deciding where a change belongs:

- **New financial analytics** (metrics, data sources, calculation methods) → contribute to
  [okama](https://github.com/mbk-dev/okama) itself.
- **New MCP tools, schemas, serialization, transports, deployment, client integrations** →
  this repository.

Do not re-implement HTTP calls to `api.okama.io` here — okama already does that; import
okama classes directly.

## Development setup

The project uses [Poetry](https://python-poetry.org/) for environment and dependency
management. Python ≥ 3.11 is required (same floor as okama).

```bash
git clone https://github.com/mbk-dev/okama-mcp
cd okama-mcp
poetry install
```

Run the server from the source checkout:

```bash
poetry run okama-mcp stdio
# or
poetry run okama-mcp http --host 127.0.0.1 --port 8765
```

## Test-driven development

Any change to production code (new feature, bugfix, refactor, behavior change) must follow
TDD: **write a failing test first, then the minimal code that makes it pass**
(RED → GREEN → REFACTOR). Changes that touch only documentation, comments, or docstrings
don't need new tests.

Run the test suite:

```bash
poetry run pytest -q
```

The live-API integration test (hits `api.okama.io`, slow and network-dependent) is excluded
by default; run it explicitly when your change affects okama interaction:

```bash
poetry run pytest -m integration
```

## Code style

- Lint with ruff before submitting: `poetry run ruff check .` must report no issues.
  The ruff configuration in `pyproject.toml` is the authoritative style guide.
- Use modern Python syntax: built-in generics (`list[int]`, `dict[str, Any]`), union types
  (`X | None`), literals over constructor calls (`{}`, `[]`).
- Type hints on all function parameters and return types.
- All comments, docstrings, and documentation in **English**.
- f-strings for logging and print messages.

## Project conventions

- **Dependencies** go in **both** `pyproject.toml` (via `poetry add`) and `requirements.txt`.
- **Tool input contracts** live in `src/okama_mcp/schemas.py` as pydantic v2 models.
- **Tools are stateless** from the client's point of view: every call accepts a full spec
  (e.g. `PortfolioSpec`). Internal caching by content hash is fine; implicit session state
  is not.
- **DataFrames/Series** returned by okama must be normalized via `okama_mcp.serialization`
  before being returned from a tool; long series are truncated with head/tail/summary.
- New or changed tools must be reflected in the README tool catalog (and "Spec shapes"
  section if schemas changed).

## Submitting a pull request

1. Fork the repository and create a feature branch.
2. Make your change following TDD (tests first).
3. Make sure `poetry run pytest -q` and `poetry run ruff check .` pass.
4. Open a pull request using the PR template. Keep PRs focused — one logical change per PR.

For bugs and feature ideas, please use the issue forms — they ask for the details we need
to act quickly.

## Code of conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By participating, you are expected to uphold it.
