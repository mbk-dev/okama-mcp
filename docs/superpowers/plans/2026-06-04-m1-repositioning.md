# M1 — Repositioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reposition okama-mcp as free & self-hosted: lower the Python floor to 3.11, rewrite README and landing page, turn `deploy/` into a self-hosting example, and decommission the public `/mcp` endpoint on secondvds.

**Architecture:** No production-code changes — only `pyproject.toml`/tooling config, documentation, deploy configs, and server ops. The streamable-http transport stays in the code (it is the self-hosting mechanism). Spec: `docs/superpowers/specs/2026-06-04-free-selfhosted-v1-design.md`.

**Tech Stack:** Poetry, uv (interpreter install), ruff, pytest, nginx + systemd on secondvds (SSH alias `secondvds`).

**Note on TDD:** Per the user's global rule, none of these tasks change executable production logic — they are config, content, and ops. No new tests are written; the existing suite run on Python 3.11 is the verification gate (Task 1).

**Note on poetry.lock:** The user's global rule says poetry.lock must never be committed. It is currently tracked in this repo — Task 1 untracks and gitignores it. Surface this to the user before executing.

---

### Task 1: Lower Python floor to 3.11

**Files:**
- Modify: `pyproject.toml` (python constraint, ruff target-version)
- Modify: `.python-version`
- Modify: `.gitignore` (add poetry.lock)
- Delete from tracking (keep on disk): `poetry.lock`

- [ ] **Step 1: Edit `pyproject.toml`**

Change the python constraint (line 10):

```toml
python = ">=3.11,<4.0.0"
```

Change the ruff target (under `[tool.ruff]`):

```toml
target-version = "py311"
```

- [ ] **Step 2: Edit `.python-version`**

Replace the file content with:

```
3.11
```

- [ ] **Step 3: Untrack poetry.lock and gitignore it**

```bash
git rm --cached poetry.lock
echo "poetry.lock" >> .gitignore
```

- [ ] **Step 4: Install Python 3.11 and rebuild the poetry env**

```bash
uv python install 3.11
poetry env use "$(uv python find 3.11)"
poetry install
```

Expected: `poetry install` resolves and installs all dependencies on 3.11 without errors. (This also regenerates `poetry.lock` locally — now untracked.)

- [ ] **Step 5: Verify the interpreter version**

```bash
poetry run python --version
```

Expected: `Python 3.11.x`

- [ ] **Step 6: Run the full unit suite on 3.11**

```bash
poetry run pytest -q
```

Expected: all tests PASS (same count as on 3.14). If anything fails with a syntax/stdlib incompatibility, fix the offending code to be 3.11-compatible and re-run (max 2 fix cycles per AGENTS.md, then stop and report).

- [ ] **Step 7: Run ruff on the lowered target**

```bash
poetry run ruff check .
```

Expected: no issues. Fix any reported issue (py311 target may change UP-rule suggestions).

- [ ] **Step 8: Run the live integration suite (optional but recommended — network)**

```bash
poetry run pytest -m integration -q
```

Expected: PASS (hits api.okama.io; skip if offline and note it).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .python-version .gitignore
git commit -m "chore: lower Python floor to 3.11, align with okama

okama itself requires >=3.11,<4.0.0; per the new AGENTS.md rule the
MCP wrapper keeps the identical floor. Widens the audience for local
installs (3.14 is still rare on servers). Also untracks poetry.lock
(generated artifact, per workspace policy)."
```

(Note: `git rm --cached` from Step 3 is already staged; the commit includes the deletion.)

---

### Task 2: README rewrite — self-hosted framing

**Files:**
- Modify: `README.md`

No tests (content-only change).

- [ ] **Step 1: Update the Install section (README.md:21-29)**

Replace:

```markdown
Requires Python ≥ 3.14.
```

with:

```markdown
Requires Python ≥ 3.11 (same floor as okama itself).
```

- [ ] **Step 2: Reframe the Remote section (README.md:92-100)**

Replace the whole section:

```markdown
### Remote (streamable HTTP)

```bash
# server
poetry run okama-mcp http --host 0.0.0.0 --port 8765 --path /mcp
```

Then point your MCP client at `http://<server>:8765/mcp`. For production put nginx + TLS
in front and add bearer-token auth (TODO: bearer-token support is on the roadmap).
```

with:

```markdown
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
```

- [ ] **Step 3: Add a positioning line to the intro (after README.md:19)**

After the paragraph ending `…(for remote deployment).`, adjust the wording to:

```markdown
Built on [FastMCP](https://github.com/jlowin/fastmcp). Single codebase, two transports:
`stdio` (for local clients) and `streamable-http` (for self-hosting on your own server).
okama-mcp is free and open source — no hosted service, no registration; you run it
yourself, locally or on your own server.
```

- [ ] **Step 4: Verify no stale references**

```bash
grep -n "3.14\|bearer\|mcp.okama.io" README.md
```

Expected: no matches (or only intentional ones; `mcp.okama.io` should no longer be referenced as an endpoint).

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): reframe as free & self-hosted, Python >= 3.11

Hosted-endpoint positioning and the bearer-token roadmap line are gone;
the streamable-http section now documents self-hosting with the deploy/
examples. Spec: docs/superpowers/specs/2026-06-04-free-selfhosted-v1-design.md"
```

---

### Task 3: deploy/ — self-hosting example + landing-only live vhost

**Files:**
- Create: `deploy/nginx/self-hosted.conf`
- Create: `deploy/systemd/okama-mcp.service`
- Modify: `deploy/nginx/okama-mcp.conf` (remove `/mcp` location — becomes the live landing-only vhost)

No tests (config files, not executed locally).

- [ ] **Step 1: Create `deploy/nginx/self-hosted.conf`**

Generic self-hosting example (placeholder domain, no certbot-managed lines):

```nginx
# Example nginx vhost for self-hosting okama-mcp (streamable HTTP).
# Replace mcp.example.com with your domain and obtain TLS certs (e.g. certbot).

server {
    listen 80;
    server_name mcp.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mcp.example.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    client_max_body_size 4m;

    # MCP streamable-http endpoint — SSE, so disable buffering + use long timeouts.
    location /mcp {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";

        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_connect_timeout 30s;

        chunked_transfer_encoding on;
    }
}
```

- [ ] **Step 2: Create `deploy/systemd/okama-mcp.service`**

Copy of the unit running on secondvds (verified 2026-06-04), serves as the self-hosting example:

```ini
[Unit]
Description=okama-mcp MCP server (streamable HTTP)
Documentation=https://github.com/mbk-dev/okama-mcp
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=okama_mcp
Group=okama_mcp
WorkingDirectory=/var/www/okama-mcp/app
Environment=PYTHONUNBUFFERED=1
Environment=MPLBACKEND=Agg
ExecStart=/var/www/okama-mcp/app/.venv/bin/okama-mcp http --host 127.0.0.1 --port 8765 --path /mcp
Restart=on-failure
RestartSec=5

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/www/okama-mcp
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Remove the `/mcp` location from `deploy/nginx/okama-mcp.conf`**

Delete the whole block (lines 37-56 of the current file):

```nginx
    # MCP streamable-http endpoint — SSE, so disable buffering + use long timeouts.
    location /mcp {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";

        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_connect_timeout 30s;

        chunked_transfer_encoding on;
    }
```

Add a header comment at the top of the file:

```nginx
# Live vhost for mcp.okama.io — landing page only.
# The public /mcp endpoint was decommissioned 2026-06 (free & self-hosted model);
# for self-hosting see self-hosted.conf in this directory.
```

- [ ] **Step 4: Commit**

```bash
git add deploy/nginx/self-hosted.conf deploy/systemd/okama-mcp.service deploy/nginx/okama-mcp.conf
git commit -m "feat(deploy): self-hosting examples; drop /mcp from live vhost

The public endpoint is being decommissioned per the free & self-hosted
roadmap. deploy/ now carries a generic nginx example and the hardened
systemd unit for self-hosters; okama-mcp.conf mirrors the landing-only
production vhost."
```

---

### Task 4: Landing page rewrite

**Files:**
- Modify: `deploy/nginx/index.html`

No tests (content). Visual check happens in Task 5 after deployment.

- [ ] **Step 1: Remove the public-endpoint line from the header (index.html:119-122)**

Delete:

```html
    <p>
      Public MCP endpoint: <span class="endpoint">https://mcp.okama.io/mcp</span>
      (streamable-http transport).
    </p>
```

Replace with:

```html
    <p>
      Free and open source — no hosted service, no registration.
      You run it yourself: locally or on your own server.
    </p>
```

- [ ] **Step 2: Replace the "Connect a remote client" section (index.html:138-150)**

Replace the whole `<section>` with:

```html
  <section>
    <h2>Install &amp; run locally</h2>
    <p>Requires Python ≥ 3.11 and Poetry.</p>
    <pre><code>git clone https://github.com/mbk-dev/okama-mcp
cd okama-mcp
poetry install

# stdio — for Claude Desktop, Claude Code, Cursor
poetry run okama-mcp stdio</code></pre>
    <p>
      Full setup guide and client configurations (Claude Desktop, Claude Code, Cursor):
      see the <a href="https://github.com/mbk-dev/okama-mcp#readme">README on GitHub</a>.
    </p>
  </section>
```

- [ ] **Step 3: Replace the "Run locally instead" section (old index.html:152-168) with a self-hosting section**

```html
  <section>
    <h2>Self-host on your server</h2>
    <p>
      Share one instance across your MCP clients with the streamable-http transport:
    </p>
    <pre><code>poetry run okama-mcp http --host 127.0.0.1 --port 8765 --path /mcp</code></pre>
    <p>
      Ready-made nginx and systemd examples are in the
      <a href="https://github.com/mbk-dev/okama-mcp/tree/main/deploy">deploy/</a> directory.
    </p>
  </section>
```

- [ ] **Step 4: Check for stale references**

```bash
grep -n "mcp.okama.io/mcp\|3.14\|Public MCP endpoint" deploy/nginx/index.html
```

Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add deploy/nginx/index.html
git commit -m "feat(deploy): landing page for the self-hosted model

mcp.okama.io no longer advertises a public endpoint; the page now
explains local install and self-hosting, pointing at the GitHub README
and deploy/ examples."
```

---

### Task 5: Decommission the public endpoint on secondvds (ops)

**Files (remote, via `ssh secondvds`):**
- Modify: `/etc/nginx/sites-enabled/okama-mcp.conf`
- Replace: `/var/www/okama-mcp/public/index.html`
- Service: `okama-mcp.service` (stop + disable)

Prerequisites: Tasks 3-4 committed (and pushed, with user approval) — the repo files are the source of truth for what gets deployed. `/var/www/okama-mcp/app` stays in place untouched (harmless; removal is out of scope).

- [ ] **Step 1: Deploy the new landing page**

```bash
scp deploy/nginx/index.html secondvds:/tmp/okama-mcp-index.html
ssh secondvds 'sudo cp /var/www/okama-mcp/public/index.html /var/www/okama-mcp/public/index.html.bak.2026-06-04 && sudo mv /tmp/okama-mcp-index.html /var/www/okama-mcp/public/index.html'
```

- [ ] **Step 2: Deploy the landing-only nginx vhost**

Note: the live vhost contains certbot-managed lines; do NOT copy the repo file verbatim over it. Instead, back up and remove only the `/mcp` location block:

```bash
ssh secondvds 'sudo cp /etc/nginx/sites-enabled/okama-mcp.conf /etc/nginx/sites-enabled/okama-mcp.conf.bak.2026-06-04 && sudo python3 -c "
import re
p = \"/etc/nginx/sites-enabled/okama-mcp.conf\"
s = open(p).read()
s2, n = re.subn(r\"\n    # MCP streamable-http endpoint.*?\n    \}\n\", \"\n\", s, flags=re.S)
assert n == 1, f\"expected exactly 1 /mcp block, found {n}\"
open(p, \"w\").write(s2)
"'
```

- [ ] **Step 3: Validate and reload nginx**

```bash
ssh secondvds 'sudo nginx -t && sudo systemctl reload nginx'
```

Expected: `syntax is ok` / `test is successful`.

- [ ] **Step 4: Stop and disable the service**

```bash
ssh secondvds 'sudo systemctl stop okama-mcp.service && sudo systemctl disable okama-mcp.service && systemctl is-active okama-mcp.service; systemctl is-enabled okama-mcp.service'
```

Expected output: `inactive` and `disabled`.

- [ ] **Step 5: Verify from outside**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://mcp.okama.io/        # expect 200
curl -s -o /dev/null -w "%{http_code}\n" https://mcp.okama.io/mcp     # expect 404
curl -s https://mcp.okama.io/ | grep -c "Self-host"                   # expect 1 (new landing live)
```

- [ ] **Step 6: Visual check of the landing page**

Open https://mcp.okama.io/ in a browser (or via the chrome-devtools/playwright tooling) and confirm the page renders correctly in light and dark mode — content change is verified by eyes per the user's global rule.

---

## Final verification (whole milestone)

- [ ] `poetry run pytest -q` — green on Python 3.11
- [ ] `poetry run ruff check .` — clean
- [ ] `git log --oneline` shows the four commits (floor, README, deploy, landing)
- [ ] https://mcp.okama.io/ — new landing, no public endpoint advertised
- [ ] https://mcp.okama.io/mcp — 404
- [ ] `ssh secondvds 'systemctl is-enabled okama-mcp.service'` — disabled
