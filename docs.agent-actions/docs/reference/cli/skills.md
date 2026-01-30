---
title: skills Command
description: Install AI coding assistant skills for Claude Code or OpenAI Codex
sidebar_position: 5
---

# skills Command

Skills are bundled knowledge packages that teach AI coding assistants (Claude Code, OpenAI Codex) how to work with Agent Actions workflows. Instead of explaining the framework from scratch every session, you install skills once and the assistant understands YAML syntax, field references, guards, and execution patterns.

```bash
agac skills <subcommand> [options]
```

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `list` | List available bundled skills |
| `install` | Install skills to your project |

## skills list

List available bundled skills:

```bash
agac skills list
```

## skills install

Install skills for your AI coding assistant:

```bash
agac skills install --claude   # For Claude Code
agac skills install --codex    # For OpenAI Codex
```

**Options:**

| Option | Description |
|--------|-------------|
| `--claude` | Install skills for Claude Code (`.claude/skills/`) |
| `--codex` | Install skills for OpenAI Codex (`.codex/skills/`) |
| `--force` | Overwrite existing skills |

**Examples:**

```bash
# Install for Claude Code
agac skills install --claude

# Install for OpenAI Codex
agac skills install --codex

# Update skills after upgrading agent-actions
agac skills install --claude --force
```

## What Gets Installed

Each skill includes:

```
.claude/skills/agent-actions-workflow/
├── SKILL.md           # Main skill documentation
├── references/        # Syntax reference, examples
├── scripts/           # Helper scripts for common tasks
└── assets/            # Diagrams, cheat sheets
```

Skills are project-scoped - each agent-actions project can have skills installed, and the AI assistant picks them up when you open that project.

## See Also

- [Editor Setup](../../guides/editor-setup) - LSP support for Go to Definition, Hover, Autocomplete
