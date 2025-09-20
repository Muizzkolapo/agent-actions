---
title: Welcome to Agent Actions
description: YAML-native multi-agent DAG workflows with schema-first validation
sidebar_position: 1
slug: /
---

# Welcome to Agent Actions

Agent Actions is a specialized framework for **YAML-based multi-agent DAG (Directed Acyclic Graph) workflows**. Instead of general-purpose AI tooling, Agent Actions provides a structured, deterministic approach to building repeatable AI workflows with schema-driven validation.

## What Makes Agent Actions Different

### Deterministic & Reproducible
Unlike autonomous agent frameworks, Agent Actions follows a **deterministic execution model**. Same semantic inputs always produce the same semantic outputs, making it perfect for production workflows.

### Schema-First Design
Every agent output must conform to a **JSON schema**, ensuring structured, validated results. No more unpredictable LLM responses.

### YAML-Native Configuration
Define entire workflows declaratively in YAML. No complex Python classes or hidden chain logic.

### DAG-Based Dependencies
Agent relationships are explicit and visual. Data flow and execution order are always clear.

## Key Features

- **YAML Workflow Definition**: Declarative agent orchestration
- **JSON Schema Validation**: Enforced structure for all outputs
- **Deterministic Execution**: Predictable, repeatable workflows
- **DAG Dependencies**: Clear agent relationships and data flow
- **Transformation Focus**: Agents as data transformation nodes
- **Lightweight**: Minimal dependencies, fast execution
- **Multi-Model Support**: Works with OpenAI, Anthropic, and other providers

## Quick Start

Get started with Agent Actions in just a few steps:

1. **[Install Agent Actions](./installation.md)** - Set up the framework in your environment
2. **[Getting Started Guide](./getting-started.md)** - Create your first YAML workflow
3. **[Core Concepts](./core-concepts/)** - Understand DAGs, agents, and schemas

## Ideal Use Cases

Agent Actions excels at:

- **Structured Data Processing**: Transform unstructured data into validated JSON
- **Multi-Step Analysis**: Chain agents for complex analytical workflows
- **Content Pipelines**: Repeatable content generation with validation
- **Data Transformation**: Clean, enrich, and structure data flows
- **Production AI Workflows**: Reliable, schema-validated AI processes

## How It Compares

| Feature | Agent Actions | LangChain | CrewAI |
|---------|---------------|-----------|---------|
| **Workflow Definition** | Declarative YAML + DAG | Programmatic chains | Python-based crews |
| **Execution Model** | Deterministic DAG | Flexible but complex | Autonomous negotiation |
| **Output Structure** | JSON schema enforced | No guarantees | Role-based, unvalidated |
| **Reproducibility** | Strong (same inputs → same outputs) | Variable (hidden state) | Weak (agent chatter varies) |
| **Learning Curve** | Simple YAML configs | Steep API learning | Moderate complexity |
| **Focus** | Structured workflows | General AI development | Team simulation |

## Architecture Overview

```yaml
# Simple workflow example
agents:
  - name: data_extractor
    model: gpt-4
    schema: data_schema.json
    depends_on: []

  - name: data_enricher
    model: gpt-4
    schema: enriched_schema.json
    depends_on: [data_extractor]

workflows:
  - name: process_documents
    agents: [data_extractor, data_enricher]
```

## What's Next?

Ready to build deterministic AI workflows? Start with our [Getting Started Guide](./getting-started.md) or explore [Core Concepts](./core-concepts/) to understand DAG-based agent orchestration.

**Agent Actions = Airflow for AI Agents** - structured, validated, and production-ready.