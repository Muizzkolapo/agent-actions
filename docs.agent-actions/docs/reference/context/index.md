---
title: Context System
sidebar_position: 1
---

# Context System

The context system controls how data flows between actions. It refers to upstream outputs, it controls what the LLM can see, and it passes fields to downstream actions.

## Core Concepts

| Concept | Purpose | Syntax |
|---------|---------|--------|
| **Field References** | Gets the outputs of upstream actions | `{{ action_name.field }}` |
| **Context Scope** | Controls which data an action can see and how data flows | `context_scope: {observe, drop, passthrough, seed}` |
| **Seed Data** | Loads static reference data | `seed: {name: $file:path}` |

## Learn More

- **[Field References](./field-references.md)** - The `{{ action_name.field }}` syntax that refers to upstream data
- **[Context Scope](./context-scope.md)** - Control what an action can see with observe, drop and passthrough
- **[Seed Data](./seed-data.md)** - Load static reference data into the context
