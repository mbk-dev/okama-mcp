---
name: release-okama-mcp
description: >-
  Cut and publish a new okama-mcp release end to end: bump the version in
  pyproject.toml and server.json, run tests/lint/version-consistency checks,
  sync the README and the mcp.okama.io landing page, commit + annotated tag +
  push (which triggers the PyPI and MCP-registry GitHub Actions), write GitHub
  release notes, and draft a Russian announcement for community.okama.io. Use
  when asked to "release okama-mcp", "publish a new version", "cut a release",
  "bump the version and tag", "publish to PyPI / the MCP registry", or
  "выпусти/опубликуй релиз okama-mcp".
---

# Releasing okama-mcp

Publishing is **tag-driven**: pushing a `v*` tag triggers two GitHub Actions
workflows — `release.yml` (build + publish to **PyPI** via Trusted Publishing)
and `publish-mcp-registry.yml` (wait for PyPI → GitHub OIDC → `mcp-publisher
publish` to **registry.modelcontextprotocol.io**). Your job is the steps around
that automation. Do them in order.

## Guardrails (read first)

- **PyPI versions are immutable.** A version can never be re-uploaded or reused.
  Never push a `vX.Y.Z` tag until *every* pre-flight check below is green. If a
  release fails *after* PyPI has accepted the upload, do **not** retry the same
  version — bump to the next patch and start over.
- **Three versions must match exactly:** the tag (`X.Y.Z`), `pyproject.toml`
  `[tool.poetry] version`, `server.json` top-level `version`, and `server.json`
  `packages[0].version`. Both workflows hard-fail otherwise.
- The tag push is the irreversible, outward step. Treat it like a deploy:
  get the user's go-ahead before pushing the tag.
- Never commit `poetry.lock` (it is gitignored).

## 1. Pre-flight

```bash
git checkout main && git pull --ff-only
git status --short          # must be clean
git tag --sort=-v:refname | head -3   # see the latest released version
```

Pick the new version with semver, judged against changes since the last tag:
- **patch** (`x.y.Z`) — bugfixes / docs only, no API change.
- **minor** (`x.Y.0`) — new tools or new optional params, backward compatible.
- **major** (`X.0.0`) — a breaking change to a tool/spec contract.

New okama tools or new optional parameters are **minor**.

Run the quality gates — all must be clean:

```bash
poetry run pytest -q
poetry run ruff check .
poetry run pytest -m integration   # optional but recommended: hits api.okama.io
```

## 2. Bump the version (three places, identical value)

Set `NEW=X.Y.Z`, then edit to that value:
- `pyproject.toml` → `version = "X.Y.Z"`
- `server.json` → top-level `"version": "X.Y.Z"`
- `server.json` → `packages[0].version` `"version": "X.Y.Z"`

Then run the **same consistency check the workflows run** — confirm it prints
all four equal before going further:

```bash
NEW=X.Y.Z
PYPROJECT=$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2)
SERVER=$(.venv/bin/python -c "import json;print(json.load(open('server.json'))['version'])")
PKG=$(.venv/bin/python -c "import json;print(json.load(open('server.json'))['packages'][0]['version'])")
echo "tag=$NEW pyproject=$PYPROJECT server=$SERVER pkg=$PKG"
[ "$NEW" = "$PYPROJECT" ] && [ "$NEW" = "$SERVER" ] && [ "$NEW" = "$PKG" ] && echo "CONSISTENT" || echo "MISMATCH — fix before tagging"
```

## 3. Sync the README

Per the "Release: sync the landing page with the README" rule in `AGENTS.md`,
the README is the source of truth. Make sure it matches what is actually shipping
in this version:
- Tool catalog (every registered tool present; the counts/sections accurate).
- Install / run commands, supported clients, feature highlights.

Sanity-check the registered tool count against the README:

```bash
MPLBACKEND=Agg .venv/bin/python -c "
import asyncio
from fastmcp import FastMCP
from okama_mcp.tools import register_all
m = FastMCP('t'); register_all(m)
print('registered tools:', len(asyncio.run(m.list_tools())))
"
```

## 4. Sync the mcp.okama.io landing (only if needed)

The landing is a **teaser**, not a catalog mirror: `deploy/nginx/index.html`,
served from `secondvds:/var/www/okama-mcp/public/`. Touch it only when this
release changes something the landing shows — supported clients, install/run
commands, feature highlights, or the **tool count baked into the cover image**.

- **Cover image** (`docs/images/announce-en.png` = README cover, also
  `deploy/nginx/announce-en.png` = landing hero). If the tool count changed,
  edit the count in `docs/images/src/announce-en.html`, re-render at exactly
  1200×630 and overwrite **both** PNGs. Rendering recipe (the in-repo
  `file:` protocol is blocked, so serve over HTTP):

  ```bash
  cd docs/images/src && poetry run python -m http.server 8799 --bind 127.0.0.1 &
  # headless-browser screenshot of http://127.0.0.1:8799/announce-en.html at
  # 1200x630 -> save to docs/images/announce-en.png AND deploy/nginx/announce-en.png
  # then: pkill -f "http.server 8799"
  ```

- **Deploy to secondvds** (dir owned by okama_mcp; passwordless sudo is set up;
  files are `chilango:chilango 644`). Back up first, then install + verify
  byte-identical against the repo:

  ```bash
  D=$(date +%F)
  ssh secondvds "sudo cp -p /var/www/okama-mcp/public/index.html /var/www/okama-mcp/public/index.html.bak.$D" 2>/dev/null || true
  scp -q deploy/nginx/index.html secondvds:/tmp/index.html
  ssh secondvds "sudo cp /tmp/index.html /var/www/okama-mcp/public/index.html && sudo chown chilango:chilango /var/www/okama-mcp/public/index.html && sudo chmod 644 /var/www/okama-mcp/public/index.html && rm -f /tmp/index.html"
  curl -s https://mcp.okama.io/ | diff - deploy/nginx/index.html && echo "LANDING == REPO"
  # repeat the backup/scp/cp block for announce-en.png if the cover changed
  ```

The README cover on GitHub updates automatically once `main` is pushed (it is
served from raw.githubusercontent.com); only the **landing** copy needs this
manual deploy.

## 5. Commit, tag, push

```bash
git add pyproject.toml server.json README.md deploy/ docs/images/  # whatever changed
git commit -m "release: vX.Y.Z — <one-line summary of what's new>"
git tag -a vX.Y.Z -m "vX.Y.Z — <summary>"
git push origin main
git push origin vX.Y.Z        # <-- this triggers PyPI + MCP-registry publish
```

Commit message in English (repo convention); add the project's standard
Co-Authored-By trailer.

## 6. Watch the publish and verify

```bash
gh run list --limit 4                       # find the two tag-triggered runs
gh run watch <release-run-id> --exit-status  # Release to PyPI
gh run watch <registry-run-id> --exit-status # Publish to MCP Registry
```

Confirm both are live:

```bash
curl -s -o /dev/null -w "PyPI %{http_code}\n" https://pypi.org/pypi/okama-mcp/X.Y.Z/json   # expect 200
curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=okama-mcp" \
  | .venv/bin/python -c "import sys,json;[print((s.get('server') or {}).get('version')) for s in json.load(sys.stdin).get('servers',[])]"
```

If the registry run fails on "Wait for the PyPI release to appear", PyPI was
just slow — re-run that one workflow (`gh run rerun <registry-run-id>`); do not
re-tag.

## 7. Publish GitHub release notes

The workflows publish to PyPI and the registry but do **not** create a GitHub
Release. Do it explicitly so users get a changelog:

```bash
gh release create vX.Y.Z --title "vX.Y.Z — <summary>" --notes "$(cat <<'EOF'
## What's new
- <new tools / enrichments>
## Changed / fixed
- <...>
## Upgrade
`uvx okama-mcp` picks up the new version automatically; pinned installs:
`pip install -U okama-mcp`.
EOF
)"
```

Group notes by New / Changed / Fixed; name each new tool. Keep it short.

## 8. Announce on community.okama.io (Russian)

Prepare a **Russian** announcement for the community forum (community.okama.io,
Discourse). Posting is outward-facing — **get the user's go-ahead before you
post.** A forum API credential **is** available at
`~/.config/secrets/discourse-okama.env` (`DISCOURSE_OKAMA_URL`,
`DISCOURSE_OKAMA_API_KEY`, `DISCOURSE_OKAMA_API_USERNAME`) — source it and post
via the Discourse REST API. Never print the key.

Write it for end users, not developers:
- Что нового простыми словами — какие вопросы теперь можно задать ИИ-ассистенту
  (например: «сравни мой портфель с бенчмарком», «какую сумму можно безопасно
  изымать в пенсии»), а не список внутренних имён инструментов.
- Как установить / как обновиться: `uvx okama-mcp` (пакет `uv` даёт команду
  `uvx`); клиенты MCP увидят новую версию в каталоге. Команды на каждого клиента
  — из README "Connect a client".
- Терминология рунета: пиши «MCP-сервер», «MCP-клиент» (так на Хабре), не «MCP
  server».
- Ссылки: репозиторий, https://mcp.okama.io/, GitHub release.
- Тон — дружелюбный, без маркетингового шума.

### Formatting — required for any post beyond a couple of paragraphs

Split the message into **sections**, and where a section is long, into
**subsections** — each titled with a real Markdown header:
- `##` for top-level sections (e.g. `## Что нового`, `## Как установить`,
  `## Как обновиться`, `## Ссылки`).
- `###` for subsections under a section.
- Do **not** fake headings with bold text (`**…**`) — use real `##`/`###` so
  Discourse renders a proper outline. A long wall of text without headers is not
  acceptable for a release announcement.

### Posting mechanics (Discourse REST API)

Every call carries the `Api-Key` and `Api-Username` headers from the env file.
- **New product line → its own top-level category.** The forum already has
  parallel ones ("Python: библиотека okama", "Финансовые виджеты", "База
  финансовых данных"). Create with `POST /categories.json` (`name`, `slug`,
  `color`). Skip if a suitable category already exists.
- **Announcement topic:** `POST /posts.json` with `title`, `raw`, `category`.
- **Hero image:** `POST /uploads.json` (multipart `file`, `type=composer`,
  `synchronous=true`) → put the returned `short_url` at the top of the post as
  `![alt|WxH](upload://…)`. Reuse the release cover (`docs/images/announce-en.png`,
  1200×630) so the tool count matches this release — don't reuse a stale render.
- **Edit a post:** `PUT /posts/{id}.json` with `{"post": {"raw": …}}`.

## Done — report

Report to the user: new version, PyPI + registry URLs, the GitHub release link,
whether the landing was redeployed, and the Russian community draft.
