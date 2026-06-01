# agent-actions — docs site

A self-contained, statically-hostable documentation site for **agent-actions**, built to replace the Docusaurus site. Custom UI (terminal/charcoal aesthetic) with a runtime markdown engine that renders your existing `.md` content — no build step required.

---

## What's inside

```
index.html            ← entry point (open this)
tokens.css            ← design tokens (colors, type, the coral "signal" accent)
styles.css            ← all component styles
app.jsx               ← shell: nav tree, theme, search wiring, tweaks
markdown.jsx          ← markdown → site renderer (code, tables, admonitions, mermaid, TOC)
home.jsx              ← landing page
components.jsx        ← code block, callouts, tree nav, icons, TOC
search.jsx            ← ⌘K / "/" command palette (full-text across all docs)
highlight.jsx         ← lightweight syntax highlighter
tweaks-panel.jsx      ← in-page theme/accent controls

index.md              ← docs home  ("overview")
installation.md
api/  guides/  reference/  tutorials/   ← all 60 doc pages (your Docusaurus content)
img/docs-site/        ← screenshots referenced by the docs
brand-kit/            ← logo/icon/lockup/wordmark/social assets (SVG + PNG)
```

The nav tree, breadcrumbs, and "on this page" TOC are **generated automatically** from the doc files and their headings.

---

## Run it

It's a static site. Any static file server works — it must be served over **HTTP** (not opened from `file://`), because the pages are fetched at runtime.

```bash
# from this folder, pick one:
npx serve .
python3 -m http.server 8000
```

Then open the printed URL.

---

## Deploying (GitHub Pages — replacing the Docusaurus site)

Your current `.github/workflows/docs-deploy.yml` runs `npm ci && npm run build` (Docusaurus) and publishes `docs.agent-actions/build/`. This site has **no build step**, so that workflow must be swapped.

**Steps to go live at `docs.runagac.com`:**

1. Replace the contents of the repo's **`docs.agent-actions/`** folder with the contents of this package (so `docs.agent-actions/index.html` exists).
2. Overwrite **`.github/workflows/docs-deploy.yml`** with the one included here (`.github/workflows/docs-deploy.yml`). It checks out the repo and uploads `docs.agent-actions/` directly — no Node, no build.
3. The included **`CNAME`** (`docs.runagac.com`) keeps the custom domain. It's already at this folder's root so it ships in the Pages artifact. (Your existing Pages domain setting also persists it.)
4. Push to `main`. The `paths: ['docs.agent-actions/**']` trigger fires and the site deploys.

Because the live site uses `baseUrl: '/'` on a custom domain, it's served at the **domain root** — the `/img/...` paths in these docs resolve correctly with no changes.

> You can delete the old Docusaurus files in `docs.agent-actions/` (`package.json`, `docusaurus.config.ts`, `sidebars.ts`, `src/`, `node_modules/`, etc.) — this site doesn't need them.

---

## Editing content

- **Add / edit a page:** drop a `.md` file in the matching folder and add its `id` to `NAV_TREE` in `app.jsx`. Frontmatter `title:` (or the first `# H1`) becomes the page title.
- **Supported markdown:** GFM tables, fenced code (yaml / bash / json / python / ts — syntax-highlighted), `:::tip` / `:::note` / `:::warning` admonitions (rendered as callouts), `mermaid` code blocks (rendered as themed diagrams), internal links between docs, and images.
- **Theme & accent:** edit `tokens.css`. The single accent is `--signal`; light/dark live under `[data-theme]`.

---

## Notes / tradeoffs

- **JSX is transpiled in the browser** via Babel standalone (loaded from CDN, like React / marked / mermaid). This keeps the "edit a file, refresh" workflow with zero tooling, at the cost of a ~1s first-load transpile and a dependency on internet access for the CDN libs. For a production build you'd precompile the JSX and self-host the libs — happy to set that up on request.
- Hosted at the site **root** for now (`/img/...`). If you need a subpath deploy, say so and I'll make the asset base configurable.
- Content is current as of the repo import; re-import to refresh.
