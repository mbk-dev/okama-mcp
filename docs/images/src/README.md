# Announcement cover sources

Sources for `docs/images/announce-en.png` (the README cover, also the hero on
https://mcp.okama.io/ as `deploy/nginx/announce-en.png`).

## Files

- `announce-en.html` — the cover layout, designed for a 1200×630 viewport.
- `make_irr_chart_en.py` — regenerates `irr_cwd_distribution_en.png`, the chart
  embedded in the cover (deterministic: fixed seed, but live okama data evolves).
- `irr_cwd_distribution_en.png` — the chart render the committed cover was built from.

## Regenerate the cover

1. (Optional) refresh the chart: `poetry run python docs/images/src/make_irr_chart_en.py` —
   then update the IRR numbers quoted in the assistant bubble of `announce-en.html`
   if they changed.
2. Update the baked-in facts in `announce-en.html`: the tool count in the footer
   (count tools registered on the server) and the client list.
3. Render the page at exactly 1200×630 (e.g. a headless-browser screenshot of the
   viewport; serve this directory over HTTP so the relative `<img>` resolves).
4. Save the render to `docs/images/announce-en.png` and `deploy/nginx/announce-en.png`,
   then deploy the landing copy (see "Release: sync the landing page with the README"
   in `AGENTS.md`).
