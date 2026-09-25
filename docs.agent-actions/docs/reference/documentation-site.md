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
# Build and serve the documentation site
agac docs

# Open http://localhost:8000
```

## CLI Commands

### `agac docs`

Scans your project, generates documentation data, and serves an interactive documentation site. Think of this as taking a snapshot of your entire project—every agentic workflow, prompt, and schema gets cataloged—then immediately launching a browsable interface.

**What it scans:**
- Agentic workflows in `artefact/rendered_workflows/` and `*/agent_config/`
- Prompts in `prompt_store/*.md` files
- Schemas in `schema/` files (`.yml`, `.yaml`, `.json`)

**Output:**
- `artefact/catalog.json` — Agentic workflow catalog
- `artefact/runs.json` — Execution history

```bash
agac docs
agac docs --port 3000
agac docs --output ./custom-artefact
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

### Logs & Events

The event explorer is where a "why did that happen?" ends. It reads the same
structured events the framework writes to `agent_io/**/logs/events.json` and the
project's own `logs/events.json`, showing the most recent slice shared across
every log:

- **Stream or grouped** — reverse-chronological rows, or collapsed by event code
  with counts and a share bar
- **Filters** — level, workflow, free text, and every `key=value` in an event's
  payload
- **Diagnostics toggle** — framework-internal events are hidden by default, the
  same way the console hides them outside a verbose run
- **Run trace** — click an `invocation_id` to see that run laid out as spans on
  a time axis

![Logs & Events](/img/docs-site/logs.png)

### Search

Find resources quickly with full-text search across agentic workflows, actions,
schemas, prompts and event codes. Press `⌘K` (or `/`) from anywhere. As your
project grows, search becomes essential for navigating between related
components.

## Deployment

The documentation site is a static HTML/CSS/JS application. After running `agac docs`, you can deploy it anywhere static files are served:

- **Local development** — `agac docs`
- **Static hosting** — Copy the docs site to any web server (S3, Netlify, etc.)
- **CI/CD** — Generate docs as part of your pipeline

:::info
The documentation site generates static files only. It does not require a backend server, but it also cannot show real-time execution data—you need to regenerate after runs complete.
:::
