---
title: Agent Actions
description: Build LLM workflows from declarative YAML and run them in your terminal
sidebar_position: 1
slug: /
---

# Agent Actions

Agent Actions is an agentic workflow engine that runs in your terminal. You define LLM workflows in YAML. The engine does the orchestration, the validation and the error recovery.

## Get started

**Prerequisites:** Python 3.11+ and an API key from any supported provider (OpenAI, Anthropic, Gemini, Groq, Cohere, Ollama).

**Install Agent Actions:**

```bash
uv pip install agent-actions

# Or with pip
pip install agent-actions
```

**Run a workflow:**

```bash
cd your-project
agac run -a my_workflow
```

Then continue with the [Quickstart](./tutorials/) →

For the configuration options, see [Installation](./installation.md). If a problem occurs, see [Troubleshooting](./guides/troubleshooting.md).

## What to build

**[Incident triage](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/incident_triage)**: Classify the severity, assess the impact, assign teams and generate response plans. Parallel evaluators aggregate their results by consensus.

**[Contract review](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/contract_reviewer)**: Split contracts into clauses and analyze the risk of each clause in parallel. Then aggregate the findings into one report and write an executive summary.

**[Review analysis](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/review_analyzer)**: A multi-model workflow for product reviews. It extracts claims, scores the quality by parallel consensus, writes draft responses for merchants and shows product insights.

**[Book catalog enrichment](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/book_catalog_enrichment)**: Add genre classifications, marketing copy, SEO keywords and reading recommendations to raw book metadata. The example shows human-in-the-loop review for editorial decisions with high stakes.

**[Product listing enrichment](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/product_listing_enrichment)**: Change raw product specifications into listings that are ready for a marketplace. The workflow uses a strict alternation of LLM actions and tool actions, conditional skips from guards, and seed data injection.

**[Support resolution](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/support_resolution)**: Triage support tickets without JSON mode. The workflow classifies, assesses the severity, routes, summarizes and writes draft responses. It uses single-value output fields that work with any model, including local Ollama.

## What Agent Actions does for you

**Build workflows from YAML:** You define your workflow in plain YAML. Agent Actions does the DAG (directed acyclic graph) orchestration, the parallelization and the dependency resolution.

**Validate every output:** Agent Actions validates the output of each action against its JSON Schema. An `expect:` block regenerates output that does not conform, up to `max_iterations` times.

**Use more than one provider:** Chain OpenAI, Anthropic, Gemini, Groq, Cohere and Ollama in the same workflow. Change the model for each action.

**Find errors before they cost money:** Pre-flight validation checks your configuration, your field references and the dependency wiring. These checks occur before Agent Actions makes any API calls.

## How it works

Write a YAML configuration:

```yaml
name: fact_summary
description: "Extract key facts and summarize them"

actions:
  - name: extract
    intent: "Extract key facts"
    prompt: "Extract key facts from: {{ source.content }}"
    schema: facts_schema
    context_scope:
      observe:
        - source.content

  - name: summarize
    intent: "Summarize the facts"
    dependencies: [extract]
    prompt: "Summarize: {{ extract.facts }}"
    context_scope:
      observe:
        - extract.facts
```

In this example, `facts_schema` is a schema file that defines a `facts` field. The workflow file is `fact_summary.yml`.

Run the workflow:

```bash
agac run -a fact_summary
```

## Next steps

- **[Installation](./installation.md)**: Configure your environment
- **[Tutorials](./tutorials/)**: Build your first workflow
- **[Guides](./guides/)**: How-to guides for specific tasks
- **[Reference](./reference/)**: Full documentation of the features
