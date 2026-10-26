# Poetry to uv migration validation

Date: 2026-10-26. Scope: local candidate in the `переход-от-poetry-к-uv` worktree; no release or remote workflow run.

## Implemented

- PEP 621 package metadata, PEP 735 test/dev groups, Hatchling build backend, and per-worktree uv environments.
- Preserved version 3.0.0, supported Python `>=3.11,<4.0.0`, five runtime dependency ranges, console entry point, and `requirements.txt` compatibility. Installed okama metadata confirms the same Python range.
- `uv.lock` is ignored. Fresh environments resolve compatible versions, preserving the previous untracked-lock policy. Both test and dev groups are installed by default.
- Orca bootstrap installs/selects Python 3.14 and synchronizes both dependency groups. The source MCP command uses `uv run --no-sync` after setup.
- CI uses uv 0.12.23 and explicit matrix Python selection; release builds use uv with Python 3.12. Both publication workflows parse `[project].version` with `tomllib`.
- Current documentation, templates, skills, and the landing-page source command were updated. Historical release notes and old plans/specs were retained.

## Results

| Check | Result |
| --- | --- |
| Local CI-equivalent matrix, Python 3.11 / 3.12 / 3.13 / 3.14 | Each: **374 passed, 35 deselected** |
| Ruff | Passed |
| Wheel and sdist build with uv | Passed |
| Wheel package files compared with a pre-migration Poetry build | Byte-identical |
| Runtime requirements, version, Python range, declared classifiers, URLs and author email | Preserved after metadata normalization |
| Wheel and sdist installed in separate clean Python 3.12 environments | Passed |
| Source, wheel and sdist stdio MCP initialization and tool discovery | Passed; 50 tools with the published Planner dependency |
| Offline rejection of a macro series supplied as an investment asset | Passed in all four stdio probes, including the disposable worktree |
| HTTP MCP initialization and tool discovery at `/mcp` | Passed; 50 tools |
| YAML parsing, version equality and direct requirements equality | Passed |
| Both publication version gates with matching and mismatching tags | Correctly accept 3.0.0 and reject 0.0.0 |
| setup-uv v9.0.0 revision | Verified against upstream tag: `c771a70e6277c0a99b617c7a806ffedaca235ff9` |

The matrix preserves CI's pinned Planner companion (`588be5855cfaebddb6725c3f4f4126a3fda72a56`) and its `PYTHONPATH` overlay. Separate local uv environments were used for the four interpreters; the development pin did not override matrix selection. These were local runs, not GitHub Actions runs.

The new backend expresses the license as `License-Expression: MIT`, combines author name/email in the standard email field, and does not synthesize Poetry's automatic Python/license classifiers. The three explicitly declared project classifiers and the supported Python range are unchanged. Documentation, examples and tests remain in the sdist; they are absent from the wheel. The wheel retains `planner_terminology.csv` and the other package data.

## Orca verification

Live repo ID: `72584a65-b10c-4efa-b33b-6d0ed03c677d`.

Readback confirmed:

- `worktreeBasePath: ../../../wt`;
- `setupAgentStartupPolicy: wait-for-setup`;
- `commandSourcePolicy: shared-only`;
- empty local setup script.

These settings already matched the required configuration; no host-local settings were changed.

A disposable Orca worktree named `uv-migration-smoke-20261026` was created with setup skipped. Candidate tracked files were copied into it because the migration was not committed. Its exact candidate `scripts.setup` was executed twice in a non-login shell, starting without `.venv` or `uv.lock`. Both executions succeeded. Interpreter and module paths pointed to that worktree, and its configured stdio MCP command completed initialization, tool discovery and the offline error-path call.

This proves bootstrap and MCP behavior in an Orca-managed checkout. Automatic setup scheduling and agent launch were not exercised together: the wait policy was verified by readback, and no additional AI agent was launched. Missing-uv and failed Python-download paths were reviewed but not induced on the host.

The disposable candidate diff was saved, tracked files restored, and its generated lock removed before requesting normal Orca worktree removal. Deletion completion and registration were checked separately. Existing Poetry environments were retained.

## Existing limitations

1. Before migration, the Poetry environment with published `okama-planner==0.4.1` produced **35 failed, 339 passed, 35 deselected**. The uv environment without the CI companion produced the same counts and failure families. The failures concern Planner functionality/schema/privacy APIs absent from the published companion; switching package managers does not resolve them. The CI companion makes all 374 tests pass. A clean wheel/sdist smoke test verifies available MCP functionality, not complete Planner acceptance. A release remains blocked on resolving the published-companion compatibility issue.
2. The skill conflict checker returned PASS for `stress-testing-portfolios`. For `release-okama-mcp`, it reported two lexical overlaps between version-bump instructions and the Python-floor rule. Checking the pre-migration skill against the same instructions produced the same two findings. Manual review finds no semantic conflict: changing a release version does not change `requires-python`. No checker-wide rules or reviewed-overlap records were modified to suppress this inherited result; there is no whole-skill PASS for the release skill.
3. GitHub CI/publication and the live landing page were not changed or executed remotely. The landing-page repository file now says `git + uv`; deployment remains part of an authorized release.

## Reproduction and evidence

Temporary evidence and validation scripts are under `tmp/uv-migration/` (gitignored): `baseline-tests.log`, `tests.log`, `matrix-3.*.log`, `matrix-summary.log`, `build.log`, `contract.log`, `orca-setup.log`, `orca-repos.json`, `accept.log`, `http-check.log`, and skill checker reports. Baseline package artifacts and candidate artifacts are retained there for comparison.

For the full unit suite, obtain the exact companion revision and use:

```bash
uv sync --all-groups
PYTHONPATH="$PWD/tmp/planner-companion/src:$PWD/src" uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv build --out-dir tmp/uv-migration/dist
```

Hands-on transport checks after setup:

```bash
uv run --no-sync okama-mcp stdio
uv run --no-sync okama-mcp http --host 127.0.0.1 --port 8765
```

Connect an MCP client to stdio or `http://127.0.0.1:8765/mcp`; verify initialization, `tools/list`, and that `get_asset_returns` rejects `{"symbols": ["RUS_RUB.RATE"]}` without attempting an asset calculation. Check that the client starts only after Orca setup finishes. Planner acceptance additionally requires the compatible companion described above.
