# agent-actions 🚀

[![GitHub Repo stars](https://img.shields.io/github/stars/Muizzkolapo/agent-actions?style=social)](https://github.com/Muizzkolapo/agent-actions/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Muizzkolapo/agent-actions?style=social)](https://github.com/Muizzkolapo/agent-actions/network/members)
[![PyPI version](https://img.shields.io/pypi/v/agent-actions.svg)](https://pypi.org/project/agent-actions/)
[![Downloads](https://img.shields.io/pypi/dm/agent-actions)](https://pypi.org/project/agent-actions/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/Muizzkolapo/agent-actions/actions/workflows/ci.yml/badge.svg)](https://github.com/Muizzkolapo/agent-actions/actions)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

agent-actions is a **declarative YAML-based framework** for orchestrating LLM workflows. Define multi-step pipelines in YAML, execute with one command, and let the framework handle dependency resolution, parallel execution, batch processing, and multi-vendor LLM support.

![preview](https://raw.githubusercontent.com/Muizzkolapo/agent-actions/main/docs/assets/dashboard-preview.svg)

Want to know more about how it works? Check out our [documentation](https://muizzkolapo.github.io/docs.agent-actions).

## ✨ Features

🤖 **Support for all major LLM providers** - Use OpenAI, Anthropic Claude, Google Gemini, Groq, Mistral, Cohere, or run locally with Ollama. Switch providers with a single config change.

✅ **Pre-flight validation** - Never waste LLM calls on broken configs. Catch schema errors, missing dependencies, template issues, and credential problems before execution.

📝 **Declarative YAML configuration** - Define complex multi-step workflows without writing code. Just describe what you want and let agent-actions figure out the execution order.

🔀 **DAG-based execution** - Automatic dependency resolution with parallel execution. Actions run as soon as their dependencies complete.

📦 **Batch processing** - Process thousands of records through provider batch APIs. Perfect for bulk data enrichment, classification, and extraction tasks.

🔄 **Reprompting & validation** - Built-in output validation with automatic LLM retry. Define schemas and let the framework ensure outputs match.

🔒 **Semantic consistency** - Same prompt, same schema, same constraints for every record. Define your workflow once and get reproducible, consistent outputs across thousands of runs.

📁 **Version control friendly** - Workflows, prompts, and schemas are plain YAML files. Track changes with git, review diffs in PRs, and roll back when needed. No black-box configs.

🛠️ **User-defined functions (UDFs)** - Extend workflows with custom Python functions. Pre-process inputs, post-process outputs, or add custom logic anywhere.

📚 **Interactive documentation** - Auto-generate a visual dashboard showing your workflow DAG, action details, schemas, and run history.

🧩 **Observability built-in** - Track every LLM call, token usage, and execution time. Debug workflows with detailed logs and visual tools.

## Supported LLM Providers

| Provider | Models | Batch API |
|----------|--------|-----------|
| **OpenAI** | GPT-4o, GPT-4o-mini, GPT-4-turbo | ✅ |
| **Anthropic** | Claude 3.5 Sonnet, Claude 3 Haiku/Opus | ✅ |
| **Google** | Gemini 1.5 Pro, Gemini 1.5 Flash | ✅ |
| **Groq** | Llama 3.1, Mixtral | ✅ |
| **Mistral** | Mistral Large, Mistral Small | ✅ |
| **Cohere** | Command R, Command R+ | Realtime only |
| **Ollama** | Llama, Mistral, Phi (local) | Realtime only |

## Installation

```bash
# Recommended
uv pip install agent-actions

# Or with pip
pip install agent-actions
```

### Quick Start

```bash
# Initialize a new project
agac init my-project
cd my-project

# Validate your workflow (catch errors before LLM calls)
agac validate

# Run the workflow
agac run
```

That's it! Your first workflow is running. Check out the [Installation guide](https://muizzkolapo.github.io/docs.agent-actions/installation) for more details.

## Example Workflow

Here's a simple e-commerce product analysis pipeline:

```yaml
name: product-analysis
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

  # Step 2: Generate SEO descriptions (depends on step 1)
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

Run it with `agac run` and agent-actions handles the rest - dependency resolution, parallel execution, and result aggregation.

## Pre-Flight Validation

One of agent-actions' most powerful features is catching errors before you waste LLM calls:

```bash
$ agac validate

Pre-Flight Validation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Schema validation passed
✅ Dependency graph valid (3 actions, 2 levels)
❌ Template error in 'fact_extractor':
   → 'referenced_in' not in context
   → Available: source, seed
   → Fix: Add to 'observe' or check variable name
✅ Input data valid (500 records)
✅ UDFs available (12/12)
✅ API keys configured

1 error found. Fix before running.
```

This catches schema errors, circular dependencies, template issues, missing UDFs, and credential problems - all before making a single LLM call.

## CLI Commands

| Command | Description |
|---------|-------------|
| `agac init <name>` | Initialize a new project |
| `agac validate` | Pre-flight validation |
| `agac run` | Execute workflow |
| `agac batch status` | Check batch job status |
| `agac batch retrieve` | Retrieve batch results |
| `agac status` | Show workflow execution status |
| `agac docs serve` | Serve interactive documentation |
| `agac list-udfs` | List available UDFs |
| `agac validate-udfs` | Validate UDF implementations |

## Logging and Observability

agent-actions uses an event-based logging system providing both user-friendly CLI output and detailed structured logs for debugging.

### Execution Output

During workflow execution, you'll see real-time progress with:
- Action start/completion with timing
- Token usage per action
- Validation results
- Error messages with context

### Controlling Verbosity

```bash
# Show debug information (all events)
agac run --verbose

# Show only warnings and errors
agac run --quiet  # Coming in next release

# Default: Show workflow progress and action results
agac run
```

### Output Artifacts

After each workflow run, agent-actions generates artifacts in your workflow directory:

```
my-workflow/
└── agent_io/
    └── target/
        ├── run_results.json    # Execution summary (status, timing, tokens)
        └── events.json         # Full event log (NDJSON format)
```

**`run_results.json`** contains:
- Workflow metadata (invocation ID, execution mode, timing)
- Per-action results (status, execution time, token usage, output folders)
- Total token counts across all actions

**`events.json`** contains:
- Detailed event stream (workflow, agent, batch, validation events)
- Complete execution trace with timestamps and correlation IDs
- Useful for debugging, analytics, and integration with external tools

### Application Logs

General application logs (if enabled) are written to:
- `logs/agent_actions.log` - Application-level logs (JSON format)

See the [Logging Architecture](https://muizzkolapo.github.io/docs.agent-actions/reference/architecture/logging) documentation for implementation details.

## Documentation

- [Installation](https://muizzkolapo.github.io/docs.agent-actions/installation) - Install and bootstrap your first project
- [Configuration Reference](https://muizzkolapo.github.io/docs.agent-actions/reference/configuration) - Full YAML schema documentation
- [CLI Reference](https://muizzkolapo.github.io/docs.agent-actions/reference/cli) - All CLI commands and options
- [Reprompting Guide](https://muizzkolapo.github.io/docs.agent-actions/reference/validation/reprompting) - Output validation and retry
- [Custom Tools Guide](https://muizzkolapo.github.io/docs.agent-actions/guides/custom-tools) - Build custom Python tool functions

## Upcoming Features

- [ ] Automatic retry for failed batch records
- [ ] MCP (Model Context Protocol) server integration
- [ ] More LLM providers and embedding models
- [ ] Visual workflow editor

## Support Us

If you find agent-actions useful, consider giving us a star on GitHub. This helps more people discover the project and motivates continued development. Your support means a lot!

**agent-actions is completely free to use.** No paid tiers, no donations, no strings attached. Just build awesome LLM workflows.

## Contribution

agent-actions is built on the idea that LLM orchestration should be simple and declarative. If you find bugs or have ideas, please share them via GitHub Issues. We welcome contributions of all kinds!

```bash
# Clone the repo
git clone https://github.com/Muizzkolapo/agent-actions.git
cd agent-actions

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

See our [Contributing Guide](CONTRIBUTING.md) for more details.

## Help and Support

If you have any questions or feedback, please feel free to reach out:

- **GitHub Issues** - [Report bugs or request features](https://github.com/Muizzkolapo/agent-actions/issues)
- **Discussions** - [Ask questions and share ideas](https://github.com/Muizzkolapo/agent-actions/discussions)
- **Security** - [Report vulnerabilities privately](SECURITY.md)

Thank you for exploring agent-actions! We're constantly working to improve the framework and expand its capabilities. Your feedback helps us make agent-actions even better. Don't forget to check back for updates and new features!

## License

This project is licensed under the [Apache License 2.0](LICENSE).
