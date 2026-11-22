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

The command does not replace a skill that is already in the target folder. If every skill is already there, the command installs nothing and says `Nothing installed.`. To replace the installed skills, add `--force`.

## Installed Files {/* #what-gets-installed */}

agent-actions ships four skills. `install` copies all of them:

| Skill | What it teaches |
|-------|-----------------|
| `agac-agent-skills` | Build, run, inspect and debug workflows: actions, context scope, guards, versions, schemas, prompts, HITL |
| `agac-operations` | Run large workflows safely: batch or online, resume, `--rerun`, `retry --all`, exit codes, `agac usage`, scale limits, and a health check of the output counts |
| `agac-expectations` | Declare output-quality rules with `expect:` blocks, and calibrate a rule before it may block records |
| `agac-blind-verification` | Check outputs with independent verifiers that never see the reference |

Each skill has this layout:

```
.claude/skills/<skill>/
├── SKILL.md           # Main skill documentation
├── references/        # Longer guides that SKILL.md links to
└── scripts/           # Helper scripts, where the skill has them
```

`agac skills list` shows each skill with the `description:` of its `SKILL.md` frontmatter.

Skills have a project scope. You can install skills in each agent-actions project. The AI assistant reads the skills when you open that project.

## See Also

- [Editor Setup](../../guides/editor-setup): LSP support for Go to Definition, Hover and Autocomplete
