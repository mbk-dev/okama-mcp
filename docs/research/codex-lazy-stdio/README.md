# Codex 0.169.0 lazy stdio startup

Validated on Valinor (Linux), 2026-11-17, against installed `codex-cli 0.169.0`
and upstream tag `rust-v0.169.0`. This is a client lifecycle investigation;
okama-mcp production code and the global Codex configuration were not changed.

## Decision

Keep the global `mcp_servers.okama.enabled = false` default. Enable okama only in
sessions that need it. `features.mcp_lazy_stdio_startup` is useful for additional
chats sharing one long-lived Codex app-server with a warm tool catalog. It does
**not** prevent the first okama startup in each independent Codex process, and
cannot reclaim existing servers belonging to other running sessions.

The feature is under development and disabled by default in 0.169.0. No proxy,
Codex patch, connection-sharing feature, or okama server change is needed to use
it. Deferred tool descriptions are a separate concern from process startup.

## Eligibility, from the tagged source

All of these conditions must hold for a regular chat to defer a new connection:

1. `mcp_lazy_stdio_startup = true` selects `DeferCachedStdio`.
2. The enabled server uses stdio and either `required = false` (the default), or
   `startup_readiness = "catalog"`. A required server with default
   `startup_readiness = "connection"` starts eagerly.
3. The runtime publication permits previous connections. Explicit reconnects
   deliberately omit that context and start eagerly. An existing reusable live
   connection can instead be retained; that is reuse, not deferred startup.
4. The server is not an explicitly selected plugin MCP server.
5. A valid nonempty tool catalog exists and includes at least one tool allowed
   by the configured tool filter.

The catalog is an **in-memory, process-scoped LRU of 32 identities**, with a
**30-minute TTL** measured from publication. It is not a disk cache warmed for
future independent CLI processes. Identity includes server name, command,
arguments, explicit environment and forwarded environment values, working
directory (including the fallback directory), environment ID/object identity,
protocol version, and client capabilities/extensions. Changing identity can
make a prior catalog ineligible even inside the same process.

Cache context is unavailable for Codex Apps, read-only-restricted registrations,
EMA auth, unresolved environment/protocol, and remotely sourced stdio environment
variables. During local stdio discovery, the cache lookup uses legacy protocol
identity; a prior legacy catalog can be reused unless a newer modern discovery
has invalidated it. Catalog validity also checks server opt-out, notification
revision/tracking compatibility, discovery generation, and TTL. An experimental server capability
`codex/tool-catalog-cache: {"cacheable": false}` disables catalog reuse; it is
explicitly a development/test capability, not a production workaround.

These guards are source-derived. The live probe covers ordinary stdio, the flag
on/off, and required connection/catalog readiness; it does not exercise every
auth, plugin, notification, expiry, or cache-eviction branch.

## Measured lifecycle

The [probe](probe.py) drives the installed app-server's JSON-RPC API without
sending model turns. It sets an isolated `CODEX_HOME` under the project `tmp/`,
starts the local `.venv/bin/okama-mcp`, and records its PID before `exec`. This
wrapper only instruments startup; it does not proxy MCP messages. Global MCP
registrations are not loaded. No production MCP instances are started for
measurement, and no unrelated processes are stopped.

`thread_unload_delay_secs = 0` is used **only in this probe** to bound cleanup;
connection sharing is explicitly disabled. Each first thread discovers the
catalog using `mcpServerStatus/list`, then unsubscribes and waits for the helper
to exit before creating the next thread. Warm deferred threads are inspected
without requesting status, because live metadata inspection can itself start a
connection. The next step calls `list_namespaces` twice through
`mcpServer/tool/call`. This is a read-only real okama tool and can access its data
service. Tool-call latency includes initialization and data access, so it is not
an isolated Python import benchmark.

The compact [evidence](evidence.json) preserves timestamps, process start ticks,
exit observations, PSS/SwapPss, catalog sizes and call durations. Full events,
responses, stderr and `/proc` snapshots remain in the corresponding ignored
`tmp/lazy-startup/validated-*` directories.

| Stage | Lazy enabled, ordinary server | Flag disabled |
| --- | --- | --- |
| First discovery in a fresh process | Starts a helper | Starts a helper |
| First thread unloaded | Helper exits | Helper exits |
| Next chat before use | No helper | Helper already started |
| Deferred chat unloaded without use | No helper ever launched | Not applicable |
| First real tool call | Starts helper and succeeds | Uses already starting/live helper |
| Second real tool call | Same PID; succeeds | Same PID; succeeds |
| Subscribed chat idle for 10 seconds | Same PID stays alive | Same PID stays alive |
| Used thread unloaded | Helper exits | Helper exits |
| App-server exits | No owned helper remains | No owned helper remains |

In the ordinary lazy run, the first call took **4.247 s**, the second **0.005 s**.
Cold discovery used **331.8 MiB PSS**; immediately after first use the helper used
**336.1 MiB PSS**. The warm unused chat had no helper, avoiding that process's
memory entirely. The eager control's warm helper used **280.7 MiB PSS** before
use; its calls took **2.005 s** and **0.003 s**. PSS fluctuates with shared-page
accounting and host activity; these are single-run observations, not averages.
All measured fresh helper `SwapPss` values were zero. This does not estimate the
swap released by closing older production sessions or extrapolate a guaranteed
saving across all sessions. Required-server variants are recorded separately in
the evidence.

An initial diagnostic attempt exceeded asyncio's default line limit when reading
the large tool catalog. A second attempt completed the lifecycle but hit an
exit-time `/proc` race. The checked-in probe uses a 4 MiB reader limit and handles
process disappearance; neither failed attempt is used for the result table.
Their exact owned processes were confirmed gone. The final successful runs are
the `validated-*` runs only.

## Shutdown and idle are different mechanisms

`mcp_lazy_stdio_startup` delays creating an eligible connection until it is
needed. It does not add a per-MCP idle timer that shuts down and later reloads a
used server in an open, subscribed chat. The live 10-second observation is only
a bounded observation; the source establishes the feature's mechanism.

Separately, app-server unloads a thread after it has **both no subscribers and no
active turn**, for `thread_unload_delay_secs` (default **60 seconds**). Unloading
that thread releases its MCP runtime. This is thread lifecycle management, not
an MCP idle reaper. The probe verifies server exit on thread unload with a zero
probe-only delay, and verifies that disposing an unused deferred runtime does
not start its helper. It does not establish how Orca subscribes/unsubscribes its
own chats. Closing a visible UI tab must not be assumed to unload a thread or
terminate an independent CLI process without checking the actual client.

## Reproduce

Use the existing worktree environment after the repository's normal uv setup.
Choose new output directories for each run; existing evidence is never replaced.
Run these sequentially:

```bash
codex --version
uv run --no-sync python docs/research/codex-lazy-stdio/probe.py lazy tmp/lazy-startup/replay-lazy
uv run --no-sync python docs/research/codex-lazy-stdio/probe.py eager tmp/lazy-startup/replay-eager
uv run --no-sync python docs/research/codex-lazy-stdio/probe.py required tmp/lazy-startup/replay-required
uv run --no-sync python docs/research/codex-lazy-stdio/probe.py required-catalog tmp/lazy-startup/replay-catalog
```

Each run should finish with `app-server-exit: live PIDs []`. Lazy and
required-catalog warm chats should show zero live helpers before use; eager and
required connection-readiness chats should show one. Both calls must succeed,
retain the same PID, and leave no helper after thread unload.

For a manual client experiment using the existing disabled global registration:

```bash
codex --enable mcp_lazy_stdio_startup -c 'mcp_servers.okama.enabled=true'
```

The command is a **process-local opt-in**. Expect the first chat in that fresh
CLI process to start okama immediately. To observe a cache benefit, use a second
chat within the same live Codex host; opening another independent Orca process
starts with a cold catalog again. Ask for `list_namespaces`, repeat it, inspect
the helper PID, and verify its exit when the owning host/thread actually exits.
There is no reason to add `required`, `startup_readiness`, or connection sharing
to the ordinary optional-server setup just for this feature.

Rollback: exit the experiment process and start normally, or use
`--disable mcp_lazy_stdio_startup`; omit the `enabled=true` override to retain the
disabled global default. This does not stop existing unrelated hosts.

## Primary sources

All links are pinned to the tested release:

- [Feature status](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/features/src/lib.rs#L1757).
- [Policy selection](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/session/mcp_runtime.rs#L384).
- [Eligibility and deferred trigger](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/codex-mcp/src/connection_manager.rs#L660).
- [Stdio/required readiness guard](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/config/src/mcp_types.rs#L332).
- [Catalog TTL, capacity, validity and identity](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/codex-mcp/src/tool_catalog_cache.rs).
- [Thread unload conditions](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/app-server/src/request_processors/thread_lifecycle.rs#L60).
- [Default unload delay](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/config/mod.rs#L4169).
