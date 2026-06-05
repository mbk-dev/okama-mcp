# okama-mcp — Development rules for AI agents

## Environment
- Project uses poetry for environment & dependency management.
- New dependencies must be added in `pyproject.toml` and additionally to `requirements.txt`.
- Use interpreter in poetry env (`poetry run python ...`).
- Always use `poetry add` instead of `pip install`.
- **All temporary files (including generated images, screenshots, scratch scripts, data
  dumps) go into the gitignored `tmp/` directory at the project root** — never into the
  repo root, `/tmp`, or source directories. Clean it up freely; nothing in `tmp/` is
  precious.

## Test-Driven Development (TDD)
Any change to production code (new feature, bugfix, refactor, behavior change) must follow TDD:
**write a failing test first, then the minimal code that makes it pass**. This overrides the default
"write code, then tests" workflow.

The required workflow is the `superpowers:test-driven-development` skill.
Cycle: **RED → verify RED → GREEN → verify GREEN → REFACTOR**.

## After any code changes:
1) Determine whether *executable Python code* was changed, not just comments or docstrings.
2) If executable code was changed — always run tests: `poetry run pytest -q`.
3) If only comments, docstrings or markdown files were changed — do not run tests.
4) If test execution reveals any failures or errors, attempt to fix them and re-run the tests.
   Do not repeat this cycle more than 2 times. If tests are still failing after that, stop and
   report the remaining issues instead of continuing.
5) Before finishing any code change, run `poetry run ruff check .` and fix every reported issue.
   If a warning is truly unavoidable, silence it with a targeted `# noqa: <CODE>` comment on the
   offending line and include a brief rationale. Never disable rules globally or use a bare `# noqa`.
6) After completing any **significant** change (new or changed tools, schema changes, transport or
   deployment changes, behavior changes — as opposed to docs/comment edits), proactively offer the
   user a **manual hands-on test**: give the exact command/config to connect (stdio or http), and a
   short checklist of what specifically to try and what correct behavior looks like — including the
   paths most affected by the change. Don't wait to be asked.

## Python style & modernization

- **Minimum supported Python version is taken from `pyproject.toml`** (the `python = "..."`
  constraint under `[tool.poetry.dependencies]`). All code must run unchanged on that minimum.
- **Keep the Python version floor aligned with the `okama` library.** Whenever you set or change
  the `python` constraint in `pyproject.toml`, check okama's own `python` constraint (its
  `pyproject.toml` / PyPI metadata) and keep the floors identical — okama-mcp must not claim
  support for Python versions okama itself does not support, nor require a higher floor without
  a documented reason.
- Write new code with modern syntax and avoid legacy forms:
  - Use built-in generics: `list[int]`, `dict[str, Any]`, `tuple[int, ...]` instead of
    `typing.List` / `Dict` / `Tuple`.
  - Use union syntax `X | Y` and `X | None` instead of `typing.Union` / `typing.Optional`.
  - Prefer literals over constructor calls: `{}`, `[]`, `set()`. Never write `dict()` for empty dict.
  - Use `dict(zip(a, b))` instead of `{k: v for k, v in zip(a, b)}` (ruff C416).
  - Use set literals `{"a", "b"}` instead of `set(["a", "b"])` (ruff C405).
  - Never use mutable default arguments (`def f(x=[])` / `x={}`). Use `None` and initialize inside.
- **Ruff configuration** is in `pyproject.toml` (`[tool.ruff.lint]`, selecting `C,E,F,W,B,UP`).
  Treat it as the authoritative style guide — if ruff is silent, the style is acceptable.

## Additional rules:
- Always write all code comments, docstrings, and documentation in **English**, even if the task
  description or existing code is in another language (e.g. Russian).
- Use type hints for all function parameters and return types.
- Use f-string formatting for all logging and print messages.

## Project-specific guidance

- This is a thin MCP wrapper around the `okama` Python library. Do **not** re-implement HTTP
  calls to `api.okama.io` — `okama` already does that. Import okama classes directly.
- Tools must be **stateless from the AI's POV**: every call accepts a full spec
  (e.g. `PortfolioSpec`). Internal caching by content-hash is fine, but no implicit session state.
- DataFrames/Series returned by okama must be normalized via `okama_mcp.serialization` before
  being returned from a tool. Long series should be truncated with head/tail/summary.
- All tool input contracts live in `okama_mcp.schemas` as pydantic v2 models.
- Headless servers: set `MPLBACKEND=Agg` before importing okama (matplotlib gets imported eagerly).
