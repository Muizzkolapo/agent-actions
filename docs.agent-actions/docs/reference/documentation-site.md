---
title: Documentation Site
sidebar_position: 10
---

# Documentation Site

As your agentic workflows grow in complexity, keeping track of all actions, schemas, and prompts becomes challenging. Agent Actions solves this with an interactive documentation site that automatically scans your project and generates a browsable interface.

The screenshot below shows the documentation site homepage. You can explore your agentic workflows, browse schemas, view prompts, and analyze execution history—all from a single interface.

![Documentation Site Overview](/img/docs-site/home.png)

## Quick Start

```bash
# Generate the catalog and serve it locally (blocks until Ctrl+C)
agac docs serve

# Open http://localhost:8000
```

For CI, generate the catalog without binding a port:

```bash
agac docs build
```

## CLI Commands

`agac docs` is a Click group with two subcommands. Each subcommand scans your
project and writes the same documentation data files; they differ only in
whether they then start an HTTP server.

**What gets scanned (by both `build` and `serve`):**
- Agentic workflows in `artefact/rendered_workflows/` and `*/agent_config/`
- Prompts in `prompt_store/*.md` files
- Schemas in `schema/` files (`.yml`, `.yaml`, `.json`)

**Output files (written into `--output`, default `artefact/`):**
- `catalog.json` — Agentic workflow catalog
- `runs.json` — Execution history (initialized empty if missing; populated by workflow runs)

### `agac docs build`

Generates `catalog.json` (and initializes `runs.json` if it does not exist) and
**exits**. Suitable for CI — does not bind a port and does not block.

```bash
agac docs build
agac docs build --output ./custom-artefact
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output` | `artefact` | Directory to write the catalog into. |

### `agac docs serve`

Runs `build`, then starts a **blocking** HTTP server on `--port` so the
generated site can be browsed locally. This command does not return until
interrupted with Ctrl+C; do not call it from CI.

```bash
agac docs serve
agac docs serve --port 3000
agac docs serve --output ./custom-artefact
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output` | `artefact` | Directory to write the catalog into before serving. |
| `-p, --port` | `8000` | HTTP port to bind. |

### `agac docs` (deprecated alias)

Calling `agac docs` with no subcommand prints a deprecation notice on stderr
and delegates to `agac docs serve`. The alias will be removed in **v0.3.0**;
migrate to the explicit subcommands at your convenience.

### `agac docs test`

Runs browser tests to verify the documentation site renders correctly.

```bash
agac docs test
agac docs test -t schemas
```

## Site Features

### Agentic Workflow Catalog

The catalog is your project's table of contents. Browse all agentic workflows with:

- **DAG Visualization** — Interactive graph showing action dependencies
- **Action List** — All actions with kind (LLM/tool), dependencies, intent
- **Configuration** — Defaults, vendor settings, context scope

The screenshot below shows a detailed agentic workflow view. Notice how the DAG visualization makes it easy to understand the execution order at a glance.

![Workflow Detail](/img/docs-site/workflow_detail.png)

### Run History

You might wonder: "How do I know if my agentic workflow is performing well over time?" The run history answers this question. View execution history for each agentic workflow:

- **Executed Actions** — Status, duration, token usage
- **Skipped Actions** — Actions filtered by guards (shown with SKIPPED badge)
- **Metrics** — Success rate, average duration, total tokens

The run history view helps you identify patterns—which actions take longest, which guards skip frequently, and where token usage spikes.

![Run History](/img/docs-site/runs.png)

### Schema Browser

Explore all schemas with field definitions, types, and validation rules. This is especially helpful when debugging schema validation errors—you can see exactly what structure is expected.

![Schema Browser](/img/docs-site/schemas.png)

### Prompt Library

View all prompts with full content and source file location. When you need to understand what an action does, the prompt library gives you the complete picture.

![Prompt Library](/img/docs-site/prompts.png)

### Search

Find resources quickly with full-text search across agentic workflows, actions, schemas, and prompts. As your project grows, search becomes essential for navigating between related components.

## Deployment

The documentation site is a static HTML/CSS/JS application. After running `agac docs build`, you can deploy it anywhere static files are served:

- **Local development** — `agac docs serve`
- **Static hosting** — Copy the docs site to any web server (S3, Netlify, etc.)
- **CI/CD** — `agac docs build` generates the catalog without binding a port

:::info
The documentation site generates static files only. It does not require a backend server, but it also cannot show real-time execution data—you need to regenerate after runs complete.
:::
