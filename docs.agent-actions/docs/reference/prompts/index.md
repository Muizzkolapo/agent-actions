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

## Learn More

- **[Prompt Store](./prompt-store.md)** - `{prompt}...{end_prompt}` syntax and organization
- **[Dynamic Dispatch](./dispatch.md)** - `dispatch_task()` for runtime prompt and schema selection
