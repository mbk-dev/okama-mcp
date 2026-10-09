# Planner major release implementation plan

> **For agentic workers:** Use superpowers:executing-plans, with TDD for executable changes. Commit/publish steps require separate authorization.

**Goal:** Prepare verified MCP 2.0.0 artifacts with local Planner client workflows.
**Architecture:** Reuse Planner validation/storage/calculation APIs; configure local tools only on stdio. Distribute the skill with the package.
**Tech Stack:** Python >=3.11, Poetry, FastMCP >=4.0.11, Planner 0.4.x with reports extra.
**Spec:** ../specs/2026-10-09-planner-major-release-design.md

## Global Constraints
- No real data, private CLI, companion edits, commits, pushes or deployment.
- Runtime Planner >=0.4.0,<0.5.0 with reports extra; 0.4.0 resolves from PyPI with okama >=4.0.0.
- Public forecast calls remain stateless; local paths cannot be chosen by tool inputs.

## Review Focus
- Lost response or process interruption must not silently create another client.
- Same-name clients require an explicit namesake decision.
- Empty brokers differ from absent brokers; unknown fields fail before writes.
- HTTP cannot register local tools despite local filesystem configuration.
- Packaged skill must survive a clean install; local report paths cannot escape.

### Task 1: Local registry boundary
Files: schemas.py, tools/clients.py, local_registry.py, transport.py;
tests/test_tool_clients.py and tests/test_local_transport.py.
Interfaces: register(mcp, database: Path); create(details, request_id, allow_duplicate).
- [x] Write MCP tests for persistence, update/residency, duplicate/retry, concurrent and pending receipts.
- [x] Verify RED: missing tools/CLI options.
- [x] Implement wrappers, receipt locking and explicit CLI initialization/configuration.
- [x] Verify GREEN with actual PlannerStore and HTTP option rejection.

### Task 2: Reports and skill distribution
Files: tools/planner_reports.py, skills.py, schemas.py, transport.py,
.agents/skills/create-client/SKILL.md and its source/Claude adapters.
Interfaces: register(mcp, output_dir, brand_path); install_skill(destination).
- [x] Write tests for local report export, filename traversal/overwrite and installer conflicts.
- [x] Verify RED, implement delegation/installer, verify GREEN.
- [x] Run skill creator validation and conflict checker; require PASS.

### Task 3: Release candidate and acceptance
Files: pyproject.toml, requirements.txt, server.json, README.md,
docs/planner.md, docs/releases/2.0.0.md, deploy/nginx/index.html,
examples/local_planner_client.py.
- [x] Update versions/floors, package skill and document companion/versioning boundary.
- [x] Run full pytest and Ruff; build wheel/sdist and inspect contents.
- [x] Clean Poetry install and synthetic stdio acceptance across server restart.
- [x] Record package versions, artifact hashes, public isolation and publication status in issue.
- [x] Independent review, verify material findings, complete candidate handoff.

### Task 4: Include the released Planner dependency
- [x] Replace the test-only source pin with mandatory Planner >=0.4.0,<0.5.0 and reports extra.
- [x] Mirror the dependency in requirements.txt and update install/release documentation.
- [x] Verify the released 0.4.0 wheel, full suite and a fresh package installation.
- [x] Record published dependency versions and verify clean indexed resolution.

## Authorized publication — 2026-10-09
The owner authorized commit/push/merge, v2.0.0 publication and landing deployment
after candidate acceptance. Follow the release skill and verify the indexed package.
