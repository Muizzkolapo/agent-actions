---
title: Prompt System
sidebar_position: 1
---

# Prompt System

How do you manage prompts across a complex agentic workflow? The prompt system provides a centralized, maintainable way to define and manage prompts for LLM actions. Rather than scattering prompts throughout your YAML configuration, you store them as Markdown files with Jinja2 templating support.

Think of the prompt store like a library: each prompt is a book you can reference by name, and templates let you customize the content with data from your agentic workflow.

## Core Concepts

| Concept | Purpose |
|---------|---------|
| **Prompt Store** | Centralized Markdown files containing prompts |
| **Prompt Tags** | `{prompt Name}...{end_prompt}` delimiters |
| **Template Variables** | `{{ source.field }}`, `{{ seed.data }}` |
| **Jinja2 Features** | Loops, conditionals, filters |
| **Dynamic Dispatch** | Runtime prompt/schema selection via UDFs |

## Learn More

- **[Prompt Store](./prompt-store.md)** - `{prompt}...{end_prompt}` syntax and best practices
- **[Dynamic Dispatch](./dispatch.md)** - `dispatch_task()` for runtime prompt and schema selection
