# Skills Module Architecture

This document maps the moving parts of `agent_actions/skills/` — the module that ships bundled documentation, reference material, and templates for AI coding assistants. It contains no runtime Python code.

---

## High-Level Overview

```
                      agent_actions/skills/
                            │
                    agac-agent-skills/           ← the only bundled skill
                            │
              ┌─────────────┼─────────────┐
              │             │             │
          SKILL.md     references/    assets/
        (descriptor)   (14 guides)   templates/
              │             │             │
              │             │         workflow.yml.template
              │             │         udf_tool.py.template
              │             │
              │        yaml-schema.md
              │        prompt-patterns.md
              │        udf-reference.md
              │        debugging-guide.md
              │        context-scope-guide.md
              │        workflow-patterns.md
              │        framework-contracts.md
              │        guards.md
              │        hitl-patterns.md
              │        reprompt-patterns.md
              │        schema-design-guide.md
              │        aggregation-patterns.md
              │        cli-reference.md
              │        data-flow-patterns.md
              │        action-anatomy.md
              │        dynamic-content-injection.md
              │
          (installed into user project via `agac skills install`)
```

This is a **docs/template payload**, not a Python package. There is no `__init__.py`, no imports, no runtime behavior. The CLI reads this directory tree with `pathlib` and copies it wholesale into the user's project.

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
   name: agac
   description: Build, configure, and debug agent-actions agentic workflows.
                Trigger on workflow YAML, UDFs, context_scope, guards, versions,
                schemas, seed data, prompts, reprompt, HITL, or debugging
                empty/filtered/mismatched output.
   ---
   ```
   The `description` field lists trigger keywords. AI coding assistants (Claude Code, Codex) match user queries against these keywords to decide when to load the skill.

2. **Markdown body** — the skill's primary knowledge payload. For `agac-agent-skills`, this is a comprehensive guide covering:
   - The additive bus data model
   - Record mode and FILE mode tool patterns
   - Context scope (observe / passthrough / drop)
   - Guards, versions, fan-in, seed data, schemas
   - Action templates (LLM, Record tool, FILE tool)
   - Debugging checklists
   - 15 agentic patterns with YAML examples

When an AI assistant triggers on the skill, it reads `SKILL.md` as its primary context, then follows links into `references/` for deeper detail.

---

## What the Skill Contains

### references/ (14 guides)

Deep-dive documentation that `SKILL.md` links to. Each file covers one topic in detail:

| File | Topic |
|------|-------|
| `yaml-schema.md` | Complete `agent_config/*.yml` schema reference |
| `prompt-patterns.md` | Template syntax, Jinja2, seed access, `dispatch_task()` |
| `udf-reference.md` | Record mode, FILE mode, `@udf_tool`, `TrackedItem`, `FileUDFResult` |
| `context-scope-guide.md` | observe / drop / passthrough resolution and semantics |
| `workflow-patterns.md` | Fan-in, diamond, ensemble, map-reduce topologies |
| `framework-contracts.md` | The 20 rules that govern framework behavior |
| `guards.md` | Guard conditions, `skip` vs `filter`, namespace effects |
| `debugging-guide.md` | Triage checklist for silent failures |
| `hitl-patterns.md` | Human-in-the-loop configuration and flow |
| `reprompt-patterns.md` | Validation retry with corrective feedback |
| `schema-design-guide.md` | Output schema authoring (inline and file-based) |
| `aggregation-patterns.md` | Version merge, `reduce_key`, consensus |
| `cli-reference.md` | `agac` CLI commands and flags |
| `data-flow-patterns.md` | Record lifecycle through the pipeline |
| `action-anatomy.md` | Anatomy of a single action configuration |
| `dynamic-content-injection.md` | `dispatch_task()` and dynamic prompt content |

### assets/templates/ (2 templates)

Starter files for scaffolding new workflows:

| File | Generates |
|------|-----------|
| `workflow.yml.template` | `agent_config/{workflow}.yml` — 3-step workflow skeleton with defaults, LLM action, tool action, and context scope action |
| `udf_tool.py.template` | `tools/{workflow}/*.py` — Record-mode `@udf_tool` with namespaced data access |

Templates use `{{PLACEHOLDER}}` syntax (not Jinja2). They are reference examples, not used by any automated scaffolding command — the AI assistant fills in placeholders when helping users create workflows.

---

## File Index

| File | Role |
|------|------|
| `_MANIFEST.md` | Module manifest (AMP protocol) |
| `ARCHITECTURE.md` | This file |
| `agac-agent-skills/SKILL.md` | Skill descriptor + primary knowledge payload |
| `agac-agent-skills/references/*.md` | 16 deep-dive reference guides |
| `agac-agent-skills/assets/templates/workflow.yml.template` | Workflow YAML starter template |
| `agac-agent-skills/assets/templates/udf_tool.py.template` | UDF tool starter template |

CLI entry point (outside this module):

| File | Role |
|------|------|
| `cli/skills.py` | `agac skills install` and `agac skills list` commands |

---

## Caveats

1. **No runtime code.** This module has no Python files, no `__init__.py`, no imports. It is invisible to the Python import system. The only code that touches it is `cli/skills.py`, which uses `pathlib` and `shutil`.

2. **`--force` is destructive.** `shutil.rmtree` deletes the entire target skill directory before copying. If users have edited installed skill files (customized reference docs, added notes), those edits are lost without confirmation.

3. **Bus snapshot rule.** The data model described in `SKILL.md` follows the additive bus pattern: every record's `content` dict only grows. Each action writes its output under a namespace key (`content["action_name"] = {...}`). Nothing is removed. `context_scope.observe` is the selector that controls what each action sees, but the bus carries everything. This is the foundational invariant that all reference docs assume.

4. **`seed.` prefix.** Seed data loaded via `context_scope.seed_path` is available in prompts as `{{ seed.key }}`. The config key is `seed_path:` but the template variable prefix is `seed.` — a naming asymmetry that the debugging guide calls out as a common source of confusion.

5. **Skill naming convention.** Skill directories must start with `agac-` by convention (the current skill is `agac-agent-skills`). Discovery does not enforce this — any subdirectory is treated as a skill — but the convention exists for namespace clarity.

6. **No selective update.** Installation is all-or-nothing per skill. You cannot install only `references/` or only `assets/`. The entire skill directory tree is copied.
