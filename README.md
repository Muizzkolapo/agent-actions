# agent-actions

[![PyPI version](https://img.shields.io/pypi/v/agent-actions.svg)](https://pypi.org/project/agent-actions/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/Muizzkolapo/agent-actions/actions/workflows/ci.yml/badge.svg)](https://github.com/Muizzkolapo/agent-actions/actions)
[![License: Elastic-2.0](https://img.shields.io/badge/License-Elastic--2.0-blue.svg)](LICENSE)

> Declarative YAML-based framework for orchestrating LLM workflows with batch processing

## What is agent-actions?

Define multi-step LLM workflows in YAML. Execute with one command. **agent-actions** handles dependency resolution, parallel execution, batch processing, and multi-vendor LLM support.

```yaml
# workflow.yml
name: product-analysis
version: "1.0"

actions:
  - name: extract_features
    intent: Extract key product features from description
    model_vendor: openai
    model_name: gpt-4o-mini
    schema:
      features: array
      sentiment: string

  - name: generate_summary
    intent: Generate marketing summary from features
    dependencies: [extract_features]
    observe: [extract_features.features]
```

```bash
agac run
```

## Installation

```bash
pip install agent-actions
```

## Quick Start

```bash
# Initialize a new project
agac init my-project
cd my-project

# Run the workflow
agac run
```

## Features

- **Multi-vendor LLM support** — OpenAI, Anthropic, Gemini, Groq, Mistral, Cohere, Ollama
- **Declarative YAML configuration** — Define workflows without code
- **DAG-based execution** — Automatic dependency resolution with parallel execution
- **Batch processing** — Process thousands of records with automatic retries
- **Reprompting & validation** — Built-in output validation with LLM retry
- **User-defined functions (UDFs)** — Extend with Python functions
- **Documentation generation** — Auto-generate interactive workflow docs

## CLI Commands

| Command | Description |
|---------|-------------|
| `agac init <name>` | Initialize a new project |
| `agac run` | Execute workflow |
| `agac batch status` | Check batch job status |
| `agac batch retrieve` | Retrieve batch results |
| `agac status` | Show workflow execution status |
| `agac docs serve` | Serve interactive documentation |
| `agac list-udfs` | List available UDFs |
| `agac validate-udfs` | Validate UDF implementations |
| `agac render` | Render Jinja2 templates (debugging) |
| `agac clean` | Remove temporary directories |

## Example: E-commerce Product Analysis

```yaml
name: ecommerce-pipeline
version: "1.0"

input:
  source: products.csv
  columns: [product_id, title, description]

actions:
  # Step 1: Extract features from product descriptions
  - name: feature_extraction
    intent: Extract key features, benefits, and target audience
    model_vendor: anthropic
    model_name: claude-3-haiku
    schema:
      features: array
      benefits: array
      target_audience: string

  # Step 2: Generate SEO-optimized descriptions (depends on step 1)
  - name: seo_description
    intent: Generate SEO-optimized product description
    dependencies: [feature_extraction]
    observe: [feature_extraction.features, feature_extraction.benefits]
    model_vendor: openai
    model_name: gpt-4o-mini
    schema:
      seo_title: string
      meta_description: string
      keywords: array

  # Step 3: Sentiment analysis (runs in parallel with step 2)
  - name: sentiment_analysis
    intent: Analyze sentiment of original description
    dependencies: [feature_extraction]
    model_vendor: groq
    model_name: llama-3.1-8b-instant
    schema:
      sentiment: string
      confidence: number
```

## Batch Processing

Process large datasets efficiently with the batch API:

```bash
# Check status of running batch jobs
agac batch status

# Retrieve completed results
agac batch retrieve -o ./results
```

## Documentation

- [Getting Started Guide](https://muizzkolapo.github.io/docs.agent-actions)
- [Configuration Reference](https://muizzkolapo.github.io/docs.agent-actions/reference/configuration-schema)
- [CLI Reference](https://muizzkolapo.github.io/docs.agent-actions/reference/cli)
- [Reprompting Guide](https://muizzkolapo.github.io/docs.agent-actions/guides/reprompting)

## License

This project is licensed under the [Elastic License 2.0](LICENSE).

**You CAN:**
- Use for internal business purposes
- Modify and create derivative works
- Distribute copies

**You CANNOT:**
- Provide as a hosted/managed service to third parties
- Circumvent license key functionality

See [LICENSE](LICENSE) for the full license text.
