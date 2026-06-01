---
title: Prompt System
sidebar_position: 1
---

# Prompt System

The prompt system provides centralized management of reusable prompts as Markdown files with Jinja2 templating.

## Core Concepts

| Concept | Purpose |
|---------|---------|
| **Prompt Store** | Centralized Markdown files containing prompts |
| **Prompt Tags** | `{prompt Name}...{end_prompt}` delimiters |
| **Template Variables** | `{{ source.field }}`, `{{ seed.data }}` |
| **Dynamic Dispatch** | Runtime prompt/schema selection via tools |

## Learn More

- **[Prompt Store](./prompt-store.md)** - `{prompt}...{end_prompt}` syntax and organization
- **[Dynamic Dispatch](./dispatch.md)** - `dispatch_task()` for runtime prompt and schema selection
