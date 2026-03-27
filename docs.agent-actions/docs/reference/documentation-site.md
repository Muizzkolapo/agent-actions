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
# Generate documentation data
agac docs generate

# Serve the documentation site
agac docs serve

# Open http://localhost:8000
```

## CLI Commands

### `agac docs generate`

Scans your project and generates documentation data. Think of this as taking a snapshot of your entire project—every agentic workflow, prompt, and schema gets cataloged.

**What it scans:**
- Agentic workflows in `artefact/rendered_workflows/` and `*/agent_config/`
- Prompts in `prompt_store/*.md` files
- Schemas in `schema/` files (`.yml`, `.yaml`, `.json`)

**Output:**
- `artefact/catalog.json` — Agentic workflow catalog
- `artefact/runs.json` — Execution history

```bash
agac docs generate
agac docs generate --output ./custom-artefact
```

### `agac docs serve`

Starts HTTP server to view the documentation site.

```bash
agac docs serve
agac docs serve --port 3000
```

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

![Workflow Detail](/img/docs-site/workflows_qanalabs_quiz_gen.png)

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

The documentation site is a static HTML/CSS/JS application. After running `agac docs generate`, you can deploy it anywhere static files are served:

- **Local development** — `agac docs serve`
- **Static hosting** — Copy the docs site to any web server (S3, Netlify, etc.)
- **CI/CD** — Generate docs as part of your pipeline

:::info
The documentation site generates static files only. It does not require a backend server, but it also cannot show real-time execution data—you need to regenerate after runs complete.
:::
