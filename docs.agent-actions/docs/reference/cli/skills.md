---
title: skills Command
description: Install AI coding assistant skills for Claude Code or OpenAI Codex
sidebar_position: 5
---

# skills Command

Skills are bundled packages of knowledge. They teach AI coding assistants (Claude Code, OpenAI Codex) how to work with Agent Actions workflows. You install the skills one time. Then the assistant knows the YAML syntax, field references, guards and execution patterns. You do not have to explain the framework from the beginning in each session.

```bash
agac skills <subcommand> [options]
```

:::note[Run from Anywhere]
You can run this command from any subdirectory in your project.
:::

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `list` | List the available bundled skills |
| `install` | Install skills in your project |

## skills list

List the available bundled skills:

```bash
agac skills list
```

## skills install

Install the skills for your AI coding assistant:

```bash
agac skills install --claude   # For Claude Code
agac skills install --codex    # For OpenAI Codex
```

**Options:**

| Option | Description |
|--------|-------------|
| `--claude` | Install skills for Claude Code (`.claude/skills/`) |
| `--codex` | Install skills for OpenAI Codex (`.codex/skills/`) |
| `--force` | Overwrite the existing skills |

**Examples:**

```bash
# Install for Claude Code
agac skills install --claude

# Install for OpenAI Codex
agac skills install --codex

# Update skills after upgrading agent-actions
agac skills install --claude --force
```

## Installed Files {/* #what-gets-installed */}

Each skill contains these files:

```
.claude/skills/agac-agent-skills/
├── SKILL.md           # Main skill documentation
├── references/        # Pattern guides, context scoping, prompt engineering
└── scripts/           # Helper scripts (inspect_action, reset_workflow)
```

Skills have a project scope. You can install skills in each agent-actions project. The AI assistant reads the skills when you open that project.

## See Also

- [Editor Setup](../../guides/editor-setup): LSP support for Go to Definition, Hover and Autocomplete
