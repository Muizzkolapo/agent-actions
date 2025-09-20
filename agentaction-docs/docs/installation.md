---
title: Installation
description: How to install and set up Agent Actions
sidebar_position: 2
---

# Installation

Agent Actions requires Python 3.11 or higher. Follow these steps to get started.

## Prerequisites

- Python 3.11+
- pip or uv (recommended)

## Install from Source

Currently, Agent Actions is available as a source installation:

```bash
# Clone the repository
git clone https://github.com/your-org/agent-actions.git
cd agent-actions

# Install using uv (recommended)
uv sync

# Or install using pip
pip install -e .
```

## Install Development Dependencies

If you plan to contribute or modify Agent Actions:

```bash
# Using uv
uv sync --dev

# Or using pip
pip install -e ".[dev]"
```

## Verify Installation

Test your installation by running:

```bash
agent --help
```

You should see the Agent Actions CLI help output.

## Configuration

### Environment Variables

Create a `.env` file in your project directory with your API keys:

```env
# OpenAI
OPENAI_API_KEY=your_openai_api_key_here

# Anthropic
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Google Gemini
GOOGLE_API_KEY=your_google_api_key_here

# Other providers
GROQ_API_KEY=your_groq_api_key_here
COHERE_API_KEY=your_cohere_api_key_here
MISTRAL_API_KEY=your_mistral_api_key_here
```

### Local Models

For local models using Ollama:

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama2
```

## Next Steps

Now that you have Agent Actions installed, continue with the [Getting Started Guide](./getting-started.md) to create your first agent workflow.

## Troubleshooting

### Common Issues

**Python Version Error**
```
ERROR: Python 3.11 or higher is required
```
Make sure you're using Python 3.11+. Check with `python --version`.

**Missing Dependencies**
```
ModuleNotFoundError: No module named 'agent_actions'
```
Ensure you've installed the package correctly with `-e` flag for development installation.

**API Key Errors**
```
AuthenticationError: Invalid API key
```
Double-check your API keys in the `.env` file and ensure they're valid.

### Getting Help

If you encounter issues:

1. Check the troubleshooting documentation (coming soon)
2. Search existing [GitHub issues](https://github.com/your-org/agent-actions/issues)
3. Create a new issue with detailed error information