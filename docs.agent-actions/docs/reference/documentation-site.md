---
title: Documentation Site
sidebar_position: 10
---

# Documentation Site

When your workflows become more complex, it becomes difficult to track all actions, schemas and prompts. Agent Actions has an interactive documentation site for this problem. The site automatically scans your project and generates an interface that you can browse.

The screenshot shows the homepage of the documentation site. From this one interface, you can explore your workflows, browse schemas, view prompts and analyze the execution history.

![Documentation Site Overview](/img/docs-site/home.png)

## Quick Start

```bash
# Build and serve the documentation site
agac docs

# Open http://localhost:8000
```

## CLI Commands

### `agac docs`

Scans your project, generates documentation data and serves an interactive documentation site. The command catalogs each workflow, prompt and schema in your project. Then it immediately starts an interface that you can browse. Thus the command is similar to a snapshot of your full project.

**What it scans:**
- Workflows in `artefact/rendered_workflows/` and `*/agent_config/`
- Prompts in `.md` files in `prompt_store/`, including subdirectories
- Schemas in `schema/` files (`.yml`, `.yaml`, `.json`)

**Output:**
- `artefact/catalog.json`: The workflow catalog
- `artefact/runs.json`: The execution history

```bash
agac docs
agac docs --port 3000
agac docs --output ./custom-artefact
```

### `agac docs test`

Runs browser tests to verify that the documentation site renders correctly. The command does not start the server. It needs these items:

- Node.js
- A running docs server (`-p` sets its port, default `8890`)
- The test scripts in the project root

```bash
agac docs test
agac docs test -t schemas
```

## Site Features

### Workflow Catalog {/* #agentic-workflow-catalog */}

The catalog is the table of contents of your project. Browse all workflows with these features:

- **DAG Visualization**: An interactive graph that shows the action dependencies
- **Action List**: All actions with their kind (LLM/tool), dependencies and intent
- **Configuration**: Defaults, vendor settings and context scope

The screenshot shows the detail view of a workflow. The DAG visualization makes the execution order easy to understand quickly.

![Workflow Detail](/img/docs-site/workflow_detail.png)

### Run History

The run history shows if your workflow performs well over time. View the execution history for each workflow:

- **Run list**: Status, duration, and the number of actions that succeeded, failed or were skipped
- **Run detail**: Duration, action count, tokens, result, and a timeline with one bar for each action. The timeline shows skipped actions in a muted colour

The run history view helps you find patterns, for example which actions take longest and which actions are skipped.

![Run History](/img/docs-site/runs.png)

### Schema Browser

Explore all schemas with their field names and types. The schema browser is especially helpful when you debug schema validation errors, because it shows the exact structure that the schema expects.

![Schema Browser](/img/docs-site/schemas.png)

### Prompt Library

View all prompts with their full content and the location of their source file. The prompt library gives you the complete prompt of each action. Use it when you need to understand what an action does.

![Prompt Library](/img/docs-site/prompts.png)

### Logs & Events

The event explorer answers the question "why did that happen?". It reads the same
structured events that the framework writes to `agent_io/**/logs/events.json` and to
the `logs/events.json` file of the project. It shows the most recent slice, shared across
all logs:

- **Stream or grouped**: Rows in reverse-chronological order, or rows collapsed by
  event code, with counts and a share bar
- **Filters**: Level, workflow, free text, and each `key=value` in the payload of an
  event
- **Diagnostics toggle**: By default, the explorer hides framework-internal events.
  The console also hides these events outside a verbose run
- **Run trace**: Click an `invocation_id` to see that run as spans on a time axis

![Logs & Events](/img/docs-site/logs.png)

### Search

Find resources quickly with full-text search across workflows, actions,
schemas, prompts and tools. Press `⌘K` or `Ctrl+K` (or `/`) from any page. When your project
becomes larger, you need search to move between related components. Event
codes and messages have their own search box on the Logs & Events page.

## Deployment

The documentation site is a static HTML/CSS/JS application. After you run `agac docs`, you can deploy the site to any location that serves static files:

- **Local development**: `agac docs`
- **Static hosting**: Copy the docs site to a web server (for example S3 or Netlify)
- **CI/CD**: Generate the docs as part of your CI/CD pipeline

:::note
The documentation site generates static files only. It does not require a backend server. But it also cannot show real-time execution data.
:::

To show the data of new runs, regenerate the site after the runs complete.
