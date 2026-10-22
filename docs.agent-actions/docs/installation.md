---
title: Installation
description: How to install and set up Agent Actions
sidebar_position: 2
---

# Installation

Agent Actions is available on PyPI and can be installed with pip, pipx, or uv. Let's get you set up to run your first agentic workflow.

## Requirements

- Python 3.11 or higher
- At least one LLM provider API key (OpenAI, Anthropic, etc.)

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

You should see output like:
```
Agent Actions CLI v0.2.6
```

## Provider Configuration

Set API keys as environment variables or in a `.env` file.

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

Agent Actions automatically loads `.env` files from the current directory.

### Supported Providers

| Provider | Environment Variable | Models |
|----------|---------------------|--------|
| OpenAI | `OPENAI_API_KEY` | Any model supported by the OpenAI API |
| Anthropic | `ANTHROPIC_API_KEY` | Any model supported by the Anthropic API |
| Google | `GEMINI_API_KEY` | Any model supported by the Gemini API |
| Groq | `GROQ_API_KEY` | Any model supported by the Groq API |
| Cohere | `COHERE_API_KEY` | Any model supported by the Cohere API |
| Ollama | (local) | Any model you've pulled locally |

## Local Models with Ollama

**What if you want to run models locally without API keys?** Ollama lets you run open-source models on your own hardware. This is useful for development, privacy-sensitive workloads, or when you want to avoid API costs entirely. Note that local models may have different capabilities than cloud providers—test your agentic workflow with your target model before deploying.

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3.1

# Use in your agentic workflow
# vendor: ollama_local
# model: llama3.1
```

## Local Models with an OpenAI-compatible Server

**What if your local server speaks the OpenAI API instead?** llamafile, LM Studio and vLLM all serve the OpenAI chat API on a local port. Use the `openai` vendor and point the action at the server with `base_url`. Each action keeps its own `base_url`, so one workflow can send some actions to the local server and the rest to OpenAI.

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

Two limits apply. A `base_url` action must use `run_mode: online`, because the Batch API is served only by OpenAI; preflight refuses the combination. And give every `base_url` action a schema: without one the client asks for `json_object` output, which some local servers do not enforce. See [OpenAI-compatible servers](reference/configuration/index.md#openai-compatible-servers) for the full reference.

## Upgrading

```bash
uv pip install --upgrade agent-actions

# Or with pip
pip install --upgrade agent-actions
```

## Development Installation

For contributing to Agent Actions:

```bash
git clone https://github.com/Muizzkolapo/agent-actions.git
cd agent-actions

# Install with dev dependencies (recommended)
uv sync --dev

# Or with pip
pip install -e ".[dev]"
```

## Next Steps

Now that you have Agent Actions installed, let's build something:

- **[Tutorials](./tutorials/)** - Build your first agentic workflow
- **[CLI Reference](./reference/cli/)** - Complete command documentation
