---
title: Agent Actions
description: Build production-ready agentic workflows with declarative YAML
sidebar_position: 1
slug: /
---

# Agent Actions

An agentic workflow engine that runs in your terminal. Define LLM pipelines in YAML, and the engine handles orchestration, validation, and error recovery.

## Get started in 30 seconds

**Prerequisites:** Python 3.11+ and an API key from any supported provider (OpenAI, Anthropic, Gemini, Groq, Mistral, Ollama).

**Install Agent Actions:**

```bash
uv pip install agent-actions

# Or with pip
pip install agent-actions
```

**Start using Agent Actions:**

```bash
cd your-project
agac run -a my_workflow
```

That's it! Continue with [Quickstart (5 minutes)](./tutorials/) →

See [Installation](./installation.md) for configuration options or [Troubleshooting](./guides/troubleshooting.md) if you hit issues.

## What to build

**[Incident triage](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/incident_triage)** — Classify severity, assess impact, assign teams, generate response plans. Parallel evaluators with consensus aggregation.

**[Contract review](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/contract_reviewer)** — Split contracts into clauses, analyze each for risk in parallel, aggregate findings into a unified report, and produce an executive summary.

**[Review analysis](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/review_analyzer)** — Multi-model pipeline for product reviews — extract claims, score quality via parallel consensus, draft merchant responses, and surface product insights.

**[Book catalog enrichment](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/book_catalog_enrichment)** — Enrich raw book metadata with genre classifications, marketing copy, SEO keywords, and reading recommendations. Demonstrates human-in-the-loop review for high-stakes editorial decisions.

**[Product listing enrichment](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/product_listing_enrichment)** — Transform raw product specs into marketplace-ready listings with a strict LLM/Tool alternation pipeline, guard-based conditional skips, and seed data injection.

**[Support resolution](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/support_resolution)** — Triage support tickets without JSON mode — classify, assess severity, route, summarize, and draft responses using single-value output fields that work with any model, including local Ollama.

## What Agent Actions does for you

**Build pipelines from YAML:** Define your workflow in plain YAML. Agent Actions handles DAG orchestration, parallelization, and dependency resolution.

**Validate every output:** Every LLM response is validated against JSON Schema. Invalid outputs trigger automatic reprompting until they conform.

**Mix and match providers:** Chain OpenAI, Anthropic, Gemini, Groq, Mistral, and Ollama in the same workflow. Switch models per-action.

**Catch errors before they cost you:** Pre-flight validation checks your config, variables, and dependency wiring before any API calls are made.

## How it works

Write a YAML config:

```yaml
actions:
  - name: extract
    prompt: "Extract key facts from: {{ source.content }}"
    schema: facts_schema

  - name: summarize
    dependencies: extract
    prompt: "Summarize: {{ extract.facts }}"
```

Run it:

```bash
agac run -a my_workflow
```

## Next steps

- **[Installation](./installation.md)** — Configure your environment
- **[Tutorials](./tutorials/)** — Build your first workflow
- **[Guides](./guides/)** — Task-oriented how-to guides
- **[Reference](./reference/)** — Full feature documentation
