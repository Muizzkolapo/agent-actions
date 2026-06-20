# Skills Module Architecture

This document maps the moving parts of `agent_actions/skills/` — the module that ships bundled documentation, reference material, and helper scripts for AI coding assistants. It contains no runtime Python code.

---

## High-Level Overview

```
                      agent_actions/skills/
                            │
                    agac-agent-skills/           ← the only bundled skill
                            │
              ┌─────────────┼─────────────┐
              │             │             │
          SKILL.md     references/    scripts/
        (descriptor)   (5 guides)    (2 helpers)
              │             │             │
              │             │       inspect_action.py
              │             │       reset_workflow.py
              │             │
              │        workflow-patterns.md
              │        context-scoping.md
              │        loop-patterns.md
              │        pooling-approach.md
              │        prompt-engineering.md
              │
          (installed into user project via `agac skills install`)
```

This is a **docs/scripts payload**, not a Python package. There is no `__init__.py`, no imports, no runtime behavior. The CLI reads this directory tree with `pathlib` and copies it wholesale into the user's project.

---

## Skill Discovery

Discovery is **filesystem-based**, not registry-based. There is no manifest file listing skills and no plugin system.

```
get_bundled_skills_path()                 (cli/skills.py)
  │
  └─ Path(__file__).parent.parent / "skills"
       │
       └─ iterdir() → [d for d in path.iterdir() if d.is_dir()]
            │
            └─ ["agac-agent-skills"]      ← every subdirectory is a skill
```

The `list` command reads `SKILL.md` from each discovered directory to extract a description. The description comes from the YAML frontmatter `description:` field, but the current implementation reads the first non-empty, non-heading line after line 1 — so both sources need to agree.

Adding a new skill means creating a new subdirectory under `skills/` with a `SKILL.md` at its root. No registration step needed.

---

## Installation Pipeline

```
agac skills install --claude
agac skills install --codex
agac skills install --claude --force

                 ┌──────────────────────────────────────────┐
                 │            install() flow                 │
                 │                                          │
                 │  1. Resolve project root                 │
                 │     find_project_root()                  │
                 │     (walks up looking for                │
                 │      agent_actions.yml)                  │
                 │                                          │
                 │  2. Build target path                    │
                 │     --claude → .claude/skills/           │
                 │     --codex  → .codex/skills/            │
                 │                                          │
                 │  3. For each skill directory:            │
                 │     dest exists + no --force → skip      │
                 │     dest exists + --force:               │
                 │       shutil.rmtree(dest)  ← DESTRUCTIVE │
                 │       shutil.copytree(src, dest)         │
                 │     dest missing:                        │
                 │       shutil.copytree(src, dest)         │
                 │                                          │
                 │  4. Report installed / skipped           │
                 └──────────────────────────────────────────┘
```

The copy is `shutil.copytree` — a full recursive copy of the skill directory. There is no merging, diffing, or selective update. `--force` does `shutil.rmtree` first, which **destroys any user edits** in the target directory without warning.

---

## SKILL.md Descriptor and AI Trigger

Each skill has a `SKILL.md` at its root. This file serves two purposes:

1. **YAML frontmatter** — machine-readable metadata:
   ```yaml
   ---
   name: agac-agent-skills
   description: Build, run, inspect, and debug agent-actions workflows.
                Triggers on workflow YAML, UDFs, observe/passthrough/drop,
                guards, versions, schemas, seed data, prompts, HITL, running
                or resetting a pipeline, or debugging empty/filtered output.
   ---
   ```
   The `description` field lists trigger keywords. AI coding assistants (Claude Code, Codex) match user queries against these keywords to decide when to load the skill.

2. **Markdown body** — the skill's primary knowledge payload. For `agac-agent-skills`, this is a condensed guide covering:
   - The additive bus data model
   - Record-mode and File-mode tool patterns
   - Context scope (observe / passthrough / drop)
   - Guards, versions, fan-in, seed data, schemas
   - Action templates (LLM, Record tool, File tool, HITL)
   - Running and debugging via the `agac` CLI and bundled scripts

When an AI assistant triggers on the skill, it reads `SKILL.md` as its primary context, then follows links into `references/` for deeper detail and invokes `scripts/` for inspection or reset.

---

## What the Skill Contains

### references/ (5 guides)

Deep-dive documentation that `SKILL.md` links to. Each file covers one topic in detail:

| File | Topic |
|------|-------|
| `workflow-patterns.md` | Composable harness patterns (diversity extraction, expand, fan-in, pooling, loops) |
| `context-scoping.md` | observe / passthrough / drop, dependency anchor rule, wildcards vs explicit fields, common mistakes |
| `loop-patterns.md` | Verify→rewrite, aggregate threshold patterns, sequential enrichment, contract check loops |
| `pooling-approach.md` | Sequential vs parallel pooling, selection action design, pooling vs versioning |
| `prompt-engineering.md` | One unit of outcome, distil before generating, seed data, output contracts, version diversity |

### scripts/ (2 helpers)

Executable helpers an AI assistant can run on the user's behalf:

| File | Purpose |
|------|---------|
| `inspect_action.py` | Runs `agac inspect action` and `agac inspect context` for one action — shows config, dependencies, observe fields, schema, and template variable resolution side-by-side |
| `reset_workflow.py` | Soft reset (clear `.agent_status.json`) or `--full` reset (wipe `source/`, `store/`, `target/`, status) for one workflow |

Both scripts self-locate the project root by walking up for `agent_actions.yml`, so they work from any subdirectory of a user project.

---

## File Index

| File | Role |
|------|------|
| `_MANIFEST.md` | Module manifest (AMP protocol) |
| `ARCHITECTURE.md` | This file |
| `agac-agent-skills/SKILL.md` | Skill descriptor + primary knowledge payload |
| `agac-agent-skills/references/*.md` | 5 deep-dive reference guides |
| `agac-agent-skills/scripts/*.py` | 2 helper scripts (inspect, reset) |

CLI entry point (outside this module):

| File | Role |
|------|------|
| `cli/skills.py` | `agac skills install` and `agac skills list` commands |

---

## Caveats

1. **No runtime code.** This module has no Python files in the package root, no `__init__.py`, no imports. It is invisible to the Python import system. The only framework code that touches it is `cli/skills.py`, which uses `pathlib` and `shutil`. The two files under `scripts/` run standalone — they shell out to the `agac` CLI rather than importing it.

2. **`--force` is destructive.** `shutil.rmtree` deletes the entire target skill directory before copying. If users have edited installed skill files (customized reference docs, added notes), those edits are lost without confirmation.

3. **Bus snapshot rule.** The data model described in `SKILL.md` follows the additive bus pattern: every record's `content` dict only grows. Each action writes its output under a namespace key (`content["action_name"] = {...}`). Nothing is removed. `context_scope.observe` is the selector that controls what each action sees, but the bus carries everything. This is the foundational invariant that all reference docs assume.

4. **`seed.` prefix.** Seed data loaded via `context_scope.seed_path` is available in prompts as `{{ seed.key }}`. The config key is `seed_path:` but the template variable prefix is `seed.` — a naming asymmetry that the debugging guide calls out as a common source of confusion.

5. **Skill naming convention.** Skill directories must start with `agac-` by convention (the current skill is `agac-agent-skills`). Discovery does not enforce this — any subdirectory is treated as a skill — but the convention exists for namespace clarity.

6. **No selective update.** Installation is all-or-nothing per skill. You cannot install only `references/` or only `scripts/`. The entire skill directory tree is copied.
