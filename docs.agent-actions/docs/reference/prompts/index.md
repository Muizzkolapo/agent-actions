---
title: Prompt System
sidebar_position: 1
---

# Prompt System

The prompt system keeps reusable prompts in one central location, as Markdown files with Jinja2 templating.

## Core Concepts

| Concept | Purpose |
|---------|---------|
| **Prompt Store** | Central Markdown files that contain prompts |
| **Prompt Tags** | The `{prompt Name}...{end_prompt}` delimiters |
| **Template Variables** | `{{ source.field }}`, `{{ seed.data }}` |
| **Dynamic Dispatch** | Tools select the prompt or the schema at runtime |
| **Cache Points** | `{% cache_point %}` marks the end of a long part that many records share |

## Learn More

- **[Prompt Store](./prompt-store.md)** - `{prompt}...{end_prompt}` syntax and organization
- **[Dynamic Dispatch](./dispatch.md)** - `dispatch_task()` for runtime prompt and schema selection
- **[Prompt Caching](./prompt-caching.md)** - `enable_prompt_caching` and `{% cache_point %}` for Anthropic actions
