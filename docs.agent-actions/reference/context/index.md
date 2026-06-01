---
title: Context System
sidebar_position: 1
---

# Context System

The context system controls how data flows between actions—referencing upstream outputs, controlling LLM visibility, and passing fields to downstream actions.

## Core Concepts

| Concept | Purpose | Syntax |
|---------|---------|--------|
| **Field References** | Access upstream action outputs | `{{ action.field }}` |
| **Context Scope** | Control data visibility and flow | `context_scope: {observe, drop, passthrough}` |
| **Seed Data** | Load static reference data | `seed_path: {name: $file:path}` |

## Learn More

- **[Field References](./field-references.md)** - The `{{ action.field }}` syntax for referencing upstream data
- **[Context Scope](./context-scope.md)** - Control visibility with observe, drop, and passthrough
- **[Seed Data](./seed-data.md)** - Load static reference data into context
