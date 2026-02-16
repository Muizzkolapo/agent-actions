<div align="center">
  <a href="https://muizzkolapo.github.io/docs.agent-actions">
    <picture>
      <source media="(prefers-color-scheme: light)" srcset="docs.agent-actions/static/img/logo-mark-dark.svg">
      <source media="(prefers-color-scheme: dark)" srcset="docs.agent-actions/static/img/logo-mark-light.svg">
      <img alt="Agent Actions Logo" src="docs.agent-actions/static/img/logo-mark.svg" width="60%">
    </picture>
  </a>
</div>

<div align="center">
  <h3>Declarative LLM workflow orchestration.</h3>
</div>

<div align="center">
  <a href="LICENSE" target="_blank"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
  <a href="https://pypistats.org/packages/agent-actions" target="_blank"><img src="https://img.shields.io/pypi/dm/agent-actions" alt="PyPI - Downloads"></a>
  <a href="https://pypi.org/project/agent-actions/#history" target="_blank"><img src="https://img.shields.io/pypi/v/agent-actions?label=%20" alt="Version"></a>
  <a href="https://www.python.org/downloads/" target="_blank"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"></a>
  <a href="https://github.com/Muizzkolapo/agent-actions/actions" target="_blank"><img src="https://github.com/Muizzkolapo/agent-actions/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Muizzkolapo/agent-actions/stargazers" target="_blank"><img src="https://img.shields.io/github/stars/Muizzkolapo/agent-actions?style=social" alt="GitHub stars"></a>
</div>

<br>

Agent Actions is a framework for orchestrating LLM workflows using declarative YAML. Define multi-step pipelines, and let the framework handle dependency resolution, parallel execution, batch processing, and multi-vendor LLM support — all without writing orchestration code.

```bash
pip install agent-actions
```

For agent orchestration with dependency graphs, parallel execution, and batch APIs, check out the [Configuration Reference](https://muizzkolapo.github.io/docs.agent-actions/reference/configuration).

---

**Documentation**:

- [docs.agent-actions](https://muizzkolapo.github.io/docs.agent-actions) — Guides, tutorials, and conceptual overviews
- [CLI Reference](https://muizzkolapo.github.io/docs.agent-actions/reference/cli) — All CLI commands and options
- [API Reference](https://muizzkolapo.github.io/docs.agent-actions/api/logging) — Internal API documentation

**Community**: Visit [GitHub Discussions](https://github.com/Muizzkolapo/agent-actions/discussions) to ask questions, share ideas, and connect with other users.

## Why use Agent Actions?

Agent Actions helps teams build reproducible, auditable LLM pipelines through a standard YAML interface for workflows, schemas, and execution.

Use Agent Actions for:

- **Declarative YAML configuration**. Define complex multi-step workflows without writing orchestration code. Describe what you want and let Agent Actions figure out the execution order, parallelism, and data flow.
- **Multi-vendor LLM support**. Use OpenAI, Anthropic, Google Gemini, Groq, Mistral, Cohere, or Ollama. Switch providers with a single config change — no code modifications needed.
- **DAG-based parallel execution**. Automatic dependency resolution with parallel execution. Actions run as soon as their dependencies complete, maximizing throughput.
- **Batch processing at scale**. Process thousands of records through provider batch APIs. Perfect for bulk data enrichment, classification, and extraction tasks.
- **Pre-flight validation**. Catch schema errors, missing dependencies, template issues, and credential problems before making a single LLM call. Never waste tokens on broken configs.
- **Version control friendly**. Workflows, prompts, and schemas are plain YAML files. Track changes with git, review diffs in PRs, and roll back when needed. No black-box configs.

## Supported LLM providers

| Provider | Models | Batch API |
|----------|--------|-----------|
| **OpenAI** | GPT-4o, GPT-4o-mini, GPT-4-turbo | Yes |
| **Anthropic** | Claude 3.5 Sonnet, Claude 3 Haiku/Opus | Yes |
| **Google** | Gemini 1.5 Pro, Gemini 1.5 Flash | Yes |
| **Groq** | Llama 3.1, Mixtral | Yes |
| **Mistral** | Mistral Large, Mistral Small | Yes |
| **Cohere** | Command R, Command R+ | Realtime only |
| **Ollama** | Llama, Mistral, Phi (local) | Realtime only |

## Quick start

```bash
# Initialize a new project
agac init my-project
cd my-project

# Validate your workflow (catch errors before LLM calls)
agac validate

# Run the workflow
agac run
```

## Agent Actions ecosystem

While the core framework handles workflow orchestration, Agent Actions includes additional tools for the full development lifecycle:

- **[Interactive Docs Site](https://muizzkolapo.github.io/docs.agent-actions/guides/docs-site)** — Auto-generate a visual dashboard showing your workflow DAG, action details, schemas, and run history with `agac docs serve`.
- **[User-Defined Functions](https://muizzkolapo.github.io/docs.agent-actions/guides/custom-tools)** — Extend workflows with custom Python tool functions. Pre-process inputs, post-process outputs, or add custom logic anywhere in the pipeline.
- **[Reprompting & Validation](https://muizzkolapo.github.io/docs.agent-actions/reference/validation/reprompting)** — Built-in output validation with automatic LLM retry. Define schemas and let the framework ensure outputs match expectations.
- **[Observability](https://muizzkolapo.github.io/docs.agent-actions/reference/architecture/logging)** — Track every LLM call, token usage, and execution time. Debug workflows with structured event logs and `run_results.json` artifacts.

## Additional resources

- [Installation Guide](https://muizzkolapo.github.io/docs.agent-actions/installation) — Install and bootstrap your first project.
- [Configuration Reference](https://muizzkolapo.github.io/docs.agent-actions/reference/configuration) — Full YAML schema documentation.
- [Contributing Guide](CONTRIBUTING.md) — Learn how to contribute to Agent Actions.
- [Security Policy](SECURITY.md) — Report vulnerabilities privately.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
