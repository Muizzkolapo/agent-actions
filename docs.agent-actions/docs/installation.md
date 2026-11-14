---
title: Installation
description: Install and configure Agent Actions
sidebar_position: 2
---

# Installation

Agent Actions is available on PyPI. You can install it with pip, pipx or uv. This page tells you how to install Agent Actions and configure it to run your first workflow.

## Requirements

- Python 3.11 or higher
- An API key for one or more LLM providers (for example OpenAI or Anthropic)

## Quick Install

### Using uv (recommended)

```bash
uv pip install agent-actions
```

### Using pip

```bash
pip install agent-actions
```

### Using pipx (for CLI tools)

```bash
pipx install agent-actions
```

## Verify Installation

```bash
agac --version
```

The output is similar to this:
```
Agent Actions CLI v2.0.0
```

## Provider Configuration

Set the API keys as environment variables or in a `.env` file.

### Environment Variables

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# Google Gemini
export GEMINI_API_KEY="..."
```

### Using a .env File

Create a `.env` file in your project directory:

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
```

Agent Actions loads the `.env` file in the project root, the directory that holds `agent_actions.yml`.

### Supported Providers

| Provider | Environment Variable | Models |
|----------|---------------------|--------|
| OpenAI | `OPENAI_API_KEY` | Any model supported by the OpenAI API |
| Anthropic | `ANTHROPIC_API_KEY` | Any model supported by the Anthropic API |
| Google | `GEMINI_API_KEY` | Any model supported by the Gemini API |
| Groq | `GROQ_API_KEY` | Any model supported by the Groq API |
| Cohere | `COHERE_API_KEY` | Any model supported by the Cohere API |
| Ollama (local) | (none) | Any model that you pulled to your computer |
| Ollama Cloud | `OLLAMA_API_KEY` | Any model hosted on ollama.com |

## Local Models with Ollama

Ollama runs open-source models on your own hardware, without API keys. Use Ollama for development, for workloads with private data, or to have no API costs.

Local models may have different capabilities from the models of cloud providers. Before you deploy, test your workflow with your target model.

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3.1

# Use in your agentic workflow
# model_vendor: ollama_local
# model_name: llama3.1
```

## Local Models with an OpenAI-compatible Server

To use llamafile, start it as a server on port 8080. Then set `model_vendor: llamafile`. You do not need a key or a `base_url`:

```bash
./llamafile -m model.gguf --server --port 8080
```

See [Named local runtimes](reference/configuration/index.md#named-local-runtimes).

A local server can also use the OpenAI API. llamafile, LM Studio and vLLM all serve the OpenAI chat API on a local port. For these servers, use the `openai` vendor. Then set `base_url` on the action to the address of the server. Each action keeps its own `base_url`. Thus one workflow can send some actions to the local server and the other actions to OpenAI.

```bash
# Start llamafile as a server (measured with llamafile 0.10.6)
./llamafile -m model.gguf --server --port 8080 --api-key local-key

# The openai vendor still needs an API key env var; the local server may ignore its value
export LOCAL_KEY=local-key
```

```yaml
actions:
  - name: classify_local
    model_vendor: openai
    model_name: local
    base_url: http://localhost:8080/v1
    api_key: LOCAL_KEY
  - name: summarize_cloud
    model_vendor: openai
    model_name: gpt-4o-mini
```

Two limits apply:

1. A `base_url` action must use `run_mode: online`, because only OpenAI serves the Batch API. Preflight refuses the combination of `base_url` and batch mode.
2. Give each `base_url` action a schema. Without a schema, the client asks for `json_object` output, and some local servers do not enforce that output format.

For the full reference, see [OpenAI-compatible servers](reference/configuration/index.md#openai-compatible-servers).

## Upgrading

```bash
uv pip install --upgrade agent-actions

# Or with pip
pip install --upgrade agent-actions
```

## Development Installation

To contribute to Agent Actions, install the development version:

```bash
git clone https://github.com/Muizzkolapo/agent-actions.git
cd agent-actions

# Install with dev dependencies (recommended)
uv sync --dev

# Or with pip
pip install -e ".[dev]"
```

## Next Steps

After you install Agent Actions, continue with these pages:

- **[Tutorials](./tutorials/)**: Build your first workflow
- **[CLI Reference](./reference/cli/)**: The documentation of all commands
