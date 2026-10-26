# Poetry to uv Migration Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task. This document authorizes no implementation, commits, publication, or host configuration changes by itself.

**Goal:** Replace Poetry with uv for source development, Orca worktree setup, CI, and release builds while preserving the published package contract.

**Architecture:** Move package metadata to PEP 621 and development dependencies to PEP 735 groups. Use a separate `.venv` per worktree and Hatchling for packaging. Keep the existing policy of untracked lock files for this PyPI-distributed package.

**Tech stack:** uv, Hatchling, Python 3.11–3.14, pytest, Ruff, GitHub Actions, Orca.

**Spec:** The user's request is to plan the Poetry-to-uv transition, explicitly including Orca setup. The decisions below are recommendations for that implementation, not changes already applied.

## Constraints and decisions

- Preserve package version `3.0.0`, entry point `okama-mcp = okama_mcp.transport:main`, `src/okama_mcp` layout, metadata, and runtime dependency ranges.
- Preserve supported Python range `>=3.11,<4.0.0`; `.python-version` remains `3.14` for development. Verify the okama Python floor from current package metadata before implementation; report a mismatch separately rather than silently changing support.
- Preserve runtime requirements: `okama>=4.0.0`, `fastmcp>=4.0.11,<5`, `pydantic>=2.0`, `scipy>=1.11`, and `okama-planner[reports]>=0.4.0,<0.5.0`.
- Keep `requirements.txt` as a compatibility file containing the same direct runtime ranges. Do not replace it with a transitive pinned export. `pyproject.toml` is authoritative; dependency edits must update both files.
- Ignore `uv.lock`, as currently done for `poetry.lock`. Generate a local lock on initial sync; subsequent local commands reuse it. Separate fresh checkouts may resolve different compatible versions; cross-checkout reproducibility is not promised under this policy. A committed lock would be a separate policy decision.
- Keep test and dev groups separate, install both by default with `[tool.uv] default-groups = ["dev", "test"]`, and use explicit `--all-groups` in bootstrap and CI.
- Keep all temporary files, logs, isolated validation environments, and build inspection outputs under project `tmp/`.
- No production Python behavior change is intended. Validate configuration through real setup, tests, builds, and MCP handshakes; apply RED → GREEN if implementation introduces production logic.
- Do not uninstall Poetry or delete existing Poetry environments as part of migration. Other checkouts and active processes may still use them.

## Approaches considered

1. **Recommended: PEP 621 + uv + Hatchling in one coherent migration.** Removes Poetry from dependency management and the build backend; requires checking wheel/sdist contents.
2. **Transitional: uv for installation, retaining Poetry metadata/backend.** Reduces immediate packaging changes but leaves mixed tooling and requires an additional migration. Not the target state.
3. **uv with a committed lock.** Improves reproducibility of developer and CI environments, but changes the owner's existing package lock policy. Not assumed here.

## Current repository findings

- `orca.yaml` currently adds `~/.local/bin` to PATH, selects `python3.14` via Poetry, and runs `poetry install`.
- `.mcp.json` currently starts the source checkout with `poetry run okama-mcp stdio`.
- CI tests Python 3.11, 3.12, 3.13, and 3.14. It overlays Planner source pinned to `588be5855cfaebddb6725c3f4f4126a3fda72a56` via `PYTHONPATH`; preserve this during migration.
- Release builds use Python 3.12 and Poetry; PyPI uses Trusted Publishing. A separate workflow publishes the MCP registry entry.
- Both release workflows inspect the version in `pyproject.toml`; the release skill explicitly refers to `[tool.poetry]`.
- `poetry.lock` is ignored and no lock file is tracked.
- Host-local Orca requirements are documented in `AGENTS.md`: `worktreeBasePath: ../../../wt`, wait for setup before agent startup, and no local Setup Script override. These settings are not supplied by `orca.yaml`.
- Live Orca configuration was **not verified** during planning: `orca repo show --repo current --json` returned `repo_not_found`. Discover the actual repo/setup ID at implementation time; do not interpret this response as a setup defect.

## Review focus

1. Fresh worktree with no lock or environment must bootstrap without Poetry and without requiring an existing `uv.lock`.
2. CI must use each matrix Python despite the development pin of 3.14.
3. Source MCP must import this worktree's code, and server startup must not install or resolve dependencies during the handshake.
4. Built artifacts must retain package data, entry points, direct dependency ranges, and sdist-only documentation/examples/tests.
5. The existing Planner source overlay must remain visible as a compatibility limitation; a passing overlay test must not be reported as proof of the published dependency working independently.

## Task 1: Package metadata, dependencies, and local environment

**Files:** `pyproject.toml`, `.gitignore`, `requirements.txt`.

- [ ] Before editing, record the current interpreter and installed dependency versions under `tmp/uv-migration/`. Run the current Poetry test/lint commands once if its environment exists; distinguish baseline environment failures from migration regressions.
- [ ] Move `[tool.poetry]` metadata into `[project]`, including authors, license, classifiers, URLs, and `requires-python`. Move runtime dependencies to PEP 508 strings and the console command to `[project.scripts]`.
- [ ] Replace Poetry groups with `[dependency-groups]`: `test = ["pytest", "pytest-asyncio"]`, `dev = ["ruff"]`. Set both as default groups as specified above.
- [ ] Replace `poetry-core` with Hatchling in `[build-system]`. Configure wheel packaging explicitly for `src/okama_mcp`. Configure the sdist to retain the currently included `examples/`, `docs/`, and `tests/`, along with source and required project files. Exclude `tmp/`, `.venv/`, ignored locks, and local secrets.
- [ ] Add `uv.lock` to `.gitignore`; retain the `poetry.lock` ignore rule for old local environments. Preserve `.venv/` and `tmp/` ignores.
- [ ] Check `requirements.txt` against all five runtime dependency declarations, including extras and upper bounds. No change is expected if ranges remain identical.
- [ ] Run `uv python install 3.14`, then `uv sync --python 3.14 --all-groups`. Expect an editable project install, `.venv/`, and an ignored local `uv.lock`.
- [ ] Verify `uv run --no-sync python -c 'import sys, okama_mcp; print(sys.executable); print(okama_mcp.__file__)'`: paths must belong to the current worktree. Run `uv pip check` and investigate dependency changes against the baseline.

## Task 2: Orca setup and source MCP configuration

**Files:** `orca.yaml`, `.mcp.json`; host-local Orca setup settings.

- [ ] Replace `scripts.setup` with the following bootstrap. uv is a host prerequisite installed through its documented installer; a missing uv must stop setup clearly rather than silently install a global tool.

```yaml
scripts:
  setup: |
    set -euo pipefail
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null || { echo "uv is required; install uv before Orca setup" >&2; exit 1; }
    uv python install 3.14
    uv sync --python 3.14 --all-groups
```

- [ ] Set `.mcp.json` command to `uv`, args to `["run", "--no-sync", "okama-mcp", "stdio"]`. Preserve the existing transport and environment fields. `--no-sync` makes completed setup a prerequisite and avoids resolution/install work during the handshake.
- [ ] Verify uv is visible to the Orca **agent/MCP process**, as well as the setup shell. PATH exported by setup does not automatically propagate to later processes. Configure the host launch environment if necessary; keep absolute user paths out of committed `.mcp.json`.
- [ ] Resolve Orca's repository and setup IDs with the installed CLI guide. Read back `worktreeBasePath`; retain/reapply `../../../wt` using `orca project setup-update --setup <setup-id> --worktree-base-path ../../../wt` only after confirming the actual setup ID.
- [ ] Verify the repository setting **Wait for setup to complete before starting agent** is enabled. The project instructions document this as a UI setting without a CLI equivalent; check the installed guide before assuming that remains true.
- [ ] Confirm local Setup Script is empty and committed `orca.yaml` is effective. A nonempty local script can select `commandSourcePolicy: local-only` and bypass repository setup. Record readback of the effective settings.
- [ ] Verify setup creates `.venv` under the new worktree at `~/projects/rs/wt/okama-mcp/<branch>`, and does not use another tree's `VIRTUAL_ENV` or `UV_PROJECT_ENVIRONMENT`. Remove inherited overrides from the setup launch context if found.
- [ ] Run setup twice in a disposable Orca worktree of the migration revision, starting without `.venv` or `uv.lock`. Both runs must succeed; verify the second run reuses the environment and has no tracked diff. A worktree created from an uncommitted base does not contain this migration: use a committed candidate or explicitly stage the candidate files there for validation.
- [ ] Launch an MCP client after setup: verify `initialize`, `tools/list`, and one offline schema/discovery tool call. Capture stderr separately; stdout must remain valid MCP protocol output. Verify the module path belongs to the disposable worktree.
- [ ] Exercise missing-uv setup in an isolated test shell, preserving the existing host PATH outside that shell: expect a clear failure and no agent startup. Also check a clean tree where Python 3.14 must be downloaded; network/download failures must fail setup and keep the agent startup gate closed.

## Task 3: CI and release build migration

**Files:** `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/workflows/publish-mcp-registry.yml`.

- [ ] Replace Poetry installation with official `astral-sh/setup-uv`, pinned to an implementation-time verified revision. Select and record one tested uv version for CI and document local compatibility; do not opportunistically upgrade unrelated Actions.
- [ ] Preserve the CI Python matrix and `MPLBACKEND=Agg`. Set job-level `UV_PYTHON: ${{ matrix.python-version }}` so both sync and run override `.python-version`. Install with `uv sync --all-groups`.
- [ ] Preserve the Planner checkout SHA and `PYTHONPATH` overlay exactly. Run `uv run --no-sync pytest -q` with that overlay and `uv run --no-sync ruff check .`.
- [ ] Do not use `--locked` on the initial sync because a clean checkout has no lock. Do not cache/restore `uv.lock` or `.venv` as authoritative project state; uv's download/build cache may be reused.
- [ ] In release builds retain Python 3.12, set `UV_PYTHON: "3.12"`, and replace `poetry build` with `uv build`. Preserve artifact upload, PyPI Trusted Publishing, permissions, environment, and MCP registry publication.
- [ ] Update both workflows' version reads to parse `tomllib.load(...)["project"]["version"]`. Verify equality with both `server.json` versions and the tag. A mismatched version must still fail the gate.
- [ ] Validate the YAML and run the full four-version CI matrix. Collect the selected interpreter from each job; all four must match their matrix entry.

## Task 4: Documentation and durable project instructions

**Files:** `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `.agents/skills/release-okama-mcp/SKILL.md`, `.agents/skills/stress-testing-portfolios/SKILL.md`, `docs/planner.md`, `docs/planner-localization.md`, `docs/research/mcp-discovery-validation.md`, `tests/test_integration_live.py` (docstring).

- [ ] Update current source-install, test, lint, stdio, HTTP, and dependency commands: `uv sync --all-groups`, `uv run ...`, `uv add ...`, `uv add --group test ...`, and `uv add --group dev ...`. Keep public `uvx`/`pipx`/pip installation instructions valid.
- [ ] In `AGENTS.md`, replace Poetry environment instructions, manual worktree bootstrap, Python-floor lookup, and verification commands. Document `.venv`, ignored `uv.lock`, default groups, requirements compatibility, and the Orca setup/MCP ordering from Task 2.
- [ ] Update the release skill to `[project].version`, `uv build`, and the untracked `uv.lock` policy. Preserve its existing version, publication, and landing-page checks.
- [ ] Apply `instruction-files-maintenance` for instruction edits and `skill-conflict-checker` for changed skills; require the actual conflict-check PASS before delivery.
- [ ] Update active documentation and templates found by a final tracked-file Poetry search. Keep historical plans/specs and historical command evidence intact; label superseded operational guidance where needed rather than rewriting past results.
- [ ] Check `deploy/nginx/index.html` against the new README. Its current public `uvx` command should remain correct; modify only if user-facing content actually conflicts. Deployment belongs to a separately authorized release.

## Task 5: Acceptance, rollout, and rollback

- [ ] Run `uv run --no-sync pytest -q` and `uv run --no-sync ruff check .` using the existing pinned Planner overlay where required. Record plain published-dependency behavior separately. Follow the project limit of at most two fix-and-rerun cycles for test failures.
- [ ] Run `uv build --out-dir tmp/uv-migration/dist`. Inspect wheel METADATA/entry points/package data and sdist contents against a baseline build saved before migration. Verify no Poetry backend or metadata is required to build the resulting sdist.
- [ ] Create a clean validation venv under `tmp/uv-migration/`, install the built wheel with its published runtime dependencies, check imports and console entry point, and exercise an MCP handshake. Repeat installation from the sdist. Keep these checks free of source-tree `PYTHONPATH` overlays; if Planner fails here, record and resolve the independent release blocker rather than hiding it with the CI overlay.
- [ ] Perform an HTTP smoke test with `uv run --no-sync okama-mcp http --host 127.0.0.1 --port 8765`: connect an MCP client to the transport's documented endpoint and verify initialization and tool discovery. Stop only the server started for this test.
- [ ] Complete fresh Orca worktree acceptance from Task 2, including setup completion before agent launch and source MCP readiness. Remove only the disposable validation worktree after preserving its evidence and checking ownership.
- [ ] Offer hands-on acceptance commands: `uv run --no-sync okama-mcp stdio` and the HTTP command above. Checklist: agent starts after setup, tools appear, a stateless offline call works, and HTTP initialization succeeds.
- [ ] Migration is ready only when all four Python CI jobs, lint, artifact checks, clean-wheel/sdist checks, and Orca setup/MCP checks pass, or an explicitly identified independent blocker is resolved. Do not equate a passing unit suite with full acceptance.
- [ ] After implementation is authorized, prepare reviewable commits grouping metadata, setup/CI, and documentation. Commit/push/merge/release require the applicable user authorization. No version bump or publication is needed merely to prepare the migration.
- [ ] Roll back code/configuration together to the previous revision if acceptance fails. Restore host-local Orca settings only if this migration changed them, using the recorded before-values. Old Poetry environments remain available; recreate missing ones using the previous `orca.yaml`. Do not delete caches or other worktrees' environments.
- [ ] Finally check Git status/diff and Git lock files. Preserve foreign/live locks; report any unresolved lock or acceptance gap.

## Documentation references

- [uv project configuration and packaging](https://docs.astral.sh/uv/concepts/projects/config/)
- [uv dependency groups](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [uv locking, syncing, and `--no-sync`](https://docs.astral.sh/uv/concepts/projects/sync/)
- [uv in GitHub Actions, including Python matrix selection](https://docs.astral.sh/uv/guides/integration/github/)

## Planning status

Implementation authorized and applied on 2026-10-26. See [validation and remaining limitations](../../research/uv-migration-validation.md). The configuration, environments, documentation and local acceptance checks are complete. GitHub execution, publication, combined automatic Orca setup/agent-launch acceptance, and the pre-existing published-Planner compatibility issue remain outside the verified result. No host-local Orca settings required changes.
