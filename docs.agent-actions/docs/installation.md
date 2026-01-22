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

### Using pip

```bash
pip install agent-actions
```

### Using pipx (recommended for CLI tools)

```bash
pipx install agent-actions
```

### Using uv

```bash
uv pip install agent-actions
```

## Verify Installation

```bash
agac --version
```

You should see output like:
```
agent-actions 0.1.0
```

## Provider Configuration

**How does Agent Actions know which LLM to call?** It reads API keys from your environment. Think of these keys like access badges—each provider has its own badge format, and you need the right one to get through the door.

Set them as environment variables or in a `.env` file.

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
| OpenAI | `OPENAI_API_KEY` | gpt-4o, gpt-4o-mini, o1, o1-mini |
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4, claude-3-5-sonnet |
| Google | `GEMINI_API_KEY` | gemini-2.0-flash, gemini-1.5-pro |
| Groq | `GROQ_API_KEY` | llama-3.3-70b, mixtral-8x7b |
| Mistral | `MISTRAL_API_KEY` | mistral-large, mistral-medium |
| Cohere | `COHERE_API_KEY` | command-r-plus |
| Ollama | (local) | Any Ollama model |

## Local Models with Ollama

**What if you want to run models locally without API keys?** Ollama lets you run open-source models on your own hardware. This is useful for development, privacy-sensitive workloads, or when you want to avoid API costs entirely. Note that local models may have different capabilities than cloud providers—test your agentic workflow with your target model before deploying.

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3.1

# Use in your agentic workflow
# vendor: ollama
# model: llama3.1
```

## Upgrading

```bash
pip install --upgrade agent-actions
```

## Development Installation

For contributing to Agent Actions:

```bash
git clone https://github.com/Muizzkolapo/agent-actions.git
cd agent-actions

# Install with dev dependencies
pip install -e ".[dev]"

# Or using uv
uv sync --dev
```

## Shell Completion

Enable tab completion for your shell:

### Bash

```bash
agac --install-completion bash
```

### Zsh

```bash
agac --install-completion zsh
```

### Fish

```bash
agac --install-completion fish
```

## Next Steps

Now that you have Agent Actions installed, let's build something:

- **[Getting Started](./getting-started/)** - Build your first agentic workflow
- **[CLI Reference](./cli-reference/)** - Complete command documentation

## Troubleshooting

Here are solutions to common installation issues. If you encounter something not listed here, check the GitHub Issues.

### Python Version Error

```
ERROR: Requires Python >=3.11
```

Check your Python version:
```bash
python --version
```

Use pyenv or similar to install Python 3.11+.

### Command Not Found

```
agac: command not found
```

Ensure the install location is in your PATH:
```bash
# For pip
python -m agent_actions --help

# For pipx
pipx ensurepath
```

### API Key Errors

```
AuthenticationError: Invalid API key
```

Verify your API key is set correctly:
```bash
echo $OPENAI_API_KEY
```

### Getting Help

- [GitHub Issues](https://github.com/Muizzkolapo/agent-actions/issues)
- [Discussions](https://github.com/Muizzkolapo/agent-actions/discussions)
