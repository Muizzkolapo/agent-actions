# Config Module Architecture

This document maps the moving parts of `agent_actions/config/` — the module that loads, validates, merges, and resolves all configuration for the framework: workflow YAML files, environment variables, project paths, and default constants.

---

## High-Level Overview

```
                        agent_actions/config/
                              │
          ┌───────────────────┼──────────────────────┐
          │                   │                       │
    Schema & Types       Path Resolution           DI System
   (validation layer)   (project discovery)    (container + factory)
          │                   │                       │
    schema.py             paths.py              di/container.py
    types.py              path_config.py        di/configurator.py
    environment.py        project_paths.py      di/application.py
          │                   │                       │
          └─────────┬─────────┘                       │
                    │                                 │
              manager.py ◄────────────────────────────┘
           (orchestrates the full
            config loading pipeline)
```

The module has **four concerns**:

| Concern | Files | What it does |
|---------|-------|-------------|
| Schema & validation | `schema.py`, `types.py`, `environment.py` | Pydantic models for workflow YAML, typed dicts for runtime config shapes, environment settings from `.env` |
| Path resolution | `paths.py`, `path_config.py`, `project_paths.py` | Discover project root, resolve standard paths, validate directory structure |
| Defaults & constants | `defaults.py` | Zero-import default values grouped by domain (storage, locks, API, prompts) |
| DI system | `di/container.py`, `di/configurator.py`, `di/application.py`, `factory.py`, `interfaces.py` | Lightweight DI container, service registration, `ActionRunner` creation |

Supporting files: `init.py` (project scaffolding), `__init__.py` (re-exports `WorkflowConfig`).

---

## Config Loading Pipeline

This is the full path from a YAML file on disk to a running workflow. `ConfigManager` orchestrates every step.

```
┌─────────────────────────────────────────────────────────────────┐
│                    ConfigManager Pipeline                        │
│                                                                  │
│  Step 1: load_configs()                                         │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Read workflow YAML (agent_config/{name}.yml)           │     │
│  │  Read default YAML (agent_actions.yml)                  │     │
│  │  Jinja2-render both files (template vars from env)      │     │
│  │  yaml.safe_load() → raw dicts                           │     │
│  │  Resolve tool_path (workflow > default > project)       │     │
│  └──────────────────────────┬─────────────────────────────┘     │
│                             │                                    │
│  Step 2: validate_agent_name()                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Extract top-level name from config                     │     │
│  │  ENFORCE: name == config filename stem                  │     │
│  └──────────────────────────┬─────────────────────────────┘     │
│                             │                                    │
│  Step 3: get_user_agents()                                      │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Load project defaults (agent_actions.yml)              │     │
│  │  WorkflowConfig.model_validate() ← Pydantic stage 1    │     │
│  │  model_dump(exclude_unset=True) per action              │     │
│  │  Merge: project_defaults ← workflow_defaults            │     │
│  │  ActionExpander.expand_actions_to_agents()              │     │
│  │    → expands versions, chunks, etc. into agent dicts    │     │
│  └──────────────────────────┬─────────────────────────────┘     │
│                             │                                    │
│  Step 4: merge_agent_configs()                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  AgentConfig.model_validate() per agent ← stage 2       │     │
│  │  Merge: DefaultAgentConfig ← per-agent overrides        │     │
│  │  Deep-merge chunk_config specifically                    │     │
│  │  Inject tool_path into every agent config               │     │
│  └──────────────────────────┬─────────────────────────────┘     │
│                             │                                    │
│  Step 5: determine_execution_order()                            │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Normalize context_scope refs (versioned names)         │     │
│  │  infer_dependencies() from context_scope per agent      │     │
│  │  Build dependency graph (operational agents only)       │     │
│  │  topological_sort() → execution_order                   │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  Step 6: load_environment_config()                              │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Resolve .env at project root                           │     │
│  │  EnvironmentConfig (pydantic-settings) loads env vars   │     │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Two-Stage Validation

Config validation happens in two distinct Pydantic passes with different `extra` policies. This is deliberate, not accidental.

```
Stage 1: WorkflowConfig (pre-expansion)
  ├── ActionConfig    → extra="forbid"
  │   Typos in YAML action fields raise immediately.
  │   e.g. "temperture" instead of "temperature" → ValidationError
  │
  ├── DefaultsConfig  → extra="forbid"
  │   Every key a defaults block takes is a declared field,
  │   generation params included. An undeclared key names the
  │   field it resembles and the keys the block does take.
  │
  ├── StorageConfig   → extra="forbid"
  │   The workflow's own storage: block. Its values are strict,
  │   because the consumer reads the raw dict: coercing "10" here
  │   would convert only the model's copy and hand the backend
  │   the string.
  │
  └── WorkflowConfig  → extra="forbid", plus model_validator checks:
      ├── Duplicate action names
      ├── Dangling dependency references
      ├── Invalid primary_dependency references
      └── Circular dependencies (iterative DFS)

Stage 2: AgentConfig (post-expansion)
  └── AgentConfig     → extra="allow"
      The ActionExpander injects many runtime fields (agent_type,
      code_path, schema_name, tools_path, is_versioned_agent, etc.)
      that don't exist in the original YAML. extra="allow" lets
      these pass through without declaring every injected field.
```

---

## Defaults Cascade

Values flow through five layers. Later layers override earlier ones. The first non-None value wins at each merge step.

```
Layer 1: Pydantic field defaults
  ActionConfig(temperature=None, json_mode=None, ...)
  RetryConfig(max_attempts=3, on_exhausted="return_last")
  ExpectConfig(max_iterations=3, repair="auto", structural="retry")

Layer 2: Project defaults (agent_actions.yml → default_agent_config)
  default_agent_config:
    api_key: OPENAI_API_KEY
    model_name: gpt-4o-mini
    chunk_config: {chunk_size: 300, overlap: 10}

Layer 3: Workflow defaults (agent_config/{name}.yml → defaults section)
  defaults:
    model_vendor: openai
    model_name: gpt-4o
    temperature: 0.3

Layer 4: Per-action overrides (each action in the actions list)
  actions:
    - name: extract
      temperature: 0.0    ← overrides workflow default

Layer 5: Runtime injection (by ConfigManager and ActionExpander)
  model_vendor → forced to "tool" when kind=="tool"
  model_vendor → forced to "hitl" when kind=="hitl"
  tool_path → injected from resolved tool_path chain
  optional None fields → coerced to "" for downstream string safety
```

The merge in `merge_agent_configs()` is a flat dict merge (`{**defaults, **agent}`) with one exception: `chunk_config` gets a shallow deep-merge (`{**default_chunk, **agent_chunk}`).

---

## Path Resolution

### Project Root Discovery

```
find_project_root_dir(start=cwd)
  │
  │  Walk up from start directory toward filesystem root.
  │  At each level, check (in order):
  │
  ├─ Marker files: agent_actions.yml, agent_actions.yaml, .agent_actions.yml
  │    Found? → return this directory
  │
  ├─ Fallback heuristics: agent_actions/ or agent_config/ directory exists
  │    Found? → return this directory (with debug log: "fallback heuristic")
  │
  └─ Hit filesystem root → return None → ProjectRootNotFoundError
```

### PathManager Caching

```
PathManager._project_root     ← cached resolved root
PathManager._cached_cwd       ← CWD at time of resolution
PathManager._path_cache        ← cached resolved paths by type+params

Cache invalidation rules:
  1. Explicit project_root (constructor arg) → _cached_cwd = None → never invalidated
  2. CWD-resolved root → _cached_cwd = cwd at resolution time
     → invalidated if cwd changes between calls
  3. clear_cache() → resets everything
```

### Standard Path Templates

```
PathType.AGENT_CONFIG      → {agent_name}/agent_config
PathType.AGENT_IO          → {agent_name}/agent_io
PathType.TARGET            → {agent_name}/agent_io/target/{action_name}
PathType.SCHEMA            → schema
PathType.PROMPT_STORE      → prompt_store
PathType.TEMPLATES         → templates
PathType.RENDERED_WORKFLOWS → artefact/rendered_workflows
PathType.BATCH             → batch
PathType.SEED_DATA         → seed_data
```

All relative to project root.

---

## Environment Settings

`EnvironmentConfig` extends `pydantic_settings.BaseSettings` to load from `.env` and environment variables.

```
EnvironmentConfig
  ├── API keys (SecretStr, validated ≥10 chars)
  │   ├── openai_api_key
  │   ├── anthropic_api_key
  │   └── gemini_api_key
  │
  └── Runtime settings
      └── agent_actions_env    (development/staging/production)

model_config: extra="ignore"
  Unknown env vars are silently ignored — EnvironmentConfig only
  reads the keys it declares. Users can have arbitrary env vars
  in .env without causing validation errors.
```

The `.env` file path is resolved by `ConfigManager._resolve_dotenv()` relative to the project root, not the working directory.

---


## File Index

### Schema & Validation
| File | Role |
|------|------|
| `schema.py` | `WorkflowConfig` (extra=forbid), `ActionConfig` (extra=forbid), `DefaultsConfig` (extra=forbid), `StorageConfig` (extra=forbid), `RetryConfig`, `ExpectConfig`, `HitlConfig`, `VersionConfig`; cross-validation (duplicates, dangling deps, cycles) |
| `types.py` | `Granularity`, `RunMode` enums; `ActionConfigDict`, `ActionEntryDict`, `ContextScopeDict`, `GuardConfigDict`, `WhereClauseDict`, `HitlConfigDict` typed dicts |
| `environment.py` | `EnvironmentConfig` (pydantic-settings), API key validation, environment detection helpers |

### Path Resolution
| File | Role |
|------|------|
| `paths.py` | `PathManager` — project root discovery with CWD-aware cache, standard path templates, boundary-guarded `clean_path()`, permission validation |
| `path_config.py` | `find_project_root_dir()` (walk-up marker search), `load_project_config()` (YAML loader with search order), `resolve_project_root()`, `get_tool_dirs()`, `get_schema_path()`, `get_seed_data_path()` |
| `project_paths.py` | `ProjectPathsFactory.create_project_paths()` — resolves all standard directories, validates required dirs, auto-creates optional dirs |

### Config Assembly
| File | Role |
|------|------|
| `manager.py` | `ConfigManager` — orchestrates the full pipeline: YAML load, Jinja2 render, Pydantic validate, merge defaults, expand actions, infer dependencies, topological sort, environment config |
| `defaults.py` | Zero-import default constants: `StorageDefaults`, `LockDefaults`, `OllamaDefaults`, `ApiDefaults`, `SeedDataDefaults`, `PromptDefaults`, `DocsDefaults` |

### Interfaces
| File | Role |
|------|------|
| `interfaces.py` | `ILoader`, `IProcessor`, `IGenerator`, `IDataLoader`, `ISourceDataLoader` interface ABCs |

### Project Lifecycle
| File | Role |
|------|------|
| `init.py` | `ProjectInitializer` — scaffolds new projects (directories + `agent_actions.yml`) |
| `__init__.py` | Re-exports `WorkflowConfig` |

---

## Caveats

These are the non-obvious behaviors, edge cases, and invariants that will bite you if you don't know about them.

### 1. ActionConfig uses `extra="forbid"`

Any unknown key in an action definition raises a `ValidationError`. This is intentional — it catches YAML typos like `temperture` before they silently do nothing. Pydantic raises it per key, naming the key and its location. If you add a new action-level field, you must add it to `ActionConfig` in `schema.py`.

Four names get a refusal of their own before Pydantic's, and the defaults block raises the same one: `observe`, `passthrough` and `drop` belong *under* `context_scope:`, and written beside it they are what a YAML indentation slip produces. `extra_forbidden` names the key correctly and says nothing about the indentation, so the refusal does, and shows the nesting.

The fourth is `drops`, which no consumer has ever applied — every one of them reads `context_scope.drop`, so a value written under `drops` dropped nothing. Only the static analyzer's reference check ever looked at it, validating refs it would then ignore. It is refused with the others and its remedy names `drop`, because echoing the key back would move a silent no-op under `context_scope:` rather than end it.

### 2. DefaultsConfig uses `extra="forbid"`

Unlike `ActionConfig`, which leaves the refusal to Pydantic, the defaults section raises its own: it names every undeclared key, what each resembles, and then the keys the block takes. The list is unconditional — a suggestion is a string-distance match, so it lands on a real field often enough that a reader given only the guess is left with nothing when it is wrong.

The invariant that makes the strictness safe runs both ways: **a key is declared on `DefaultsConfig` if and only if something reads it out of a defaults block**.

Left to right, it is what keeps the refusal from refusing a key the framework itself goes looking for. `inherit_simple_fields` iterates `SIMPLE_CONFIG_FIELDS` and reads each of those names off the defaults dict, so one in that set and missing from the model would fail at load while the expander still asked for it. A test pins that containment.

Right to left is the side no schema check can cover, because a declared key passes validation by definition: declare a key nothing reads and a workflow setting it loads clean and gets nothing. `drops` and `observe` were that shape until they were removed — the live spelling is `context_scope: {drop: [...], observe: [...]}`, which is declared, inherited and read. `tests/unit/config/test_defaults_keys_declared_are_read.py` walks the package AST and pins this direction; add to both `DefaultsConfig` and `SIMPLE_CONFIG_FIELDS` when you add an inheritable field.

The same shape reached three surfaces beyond this one, and all four are closed by one function, `refuse_context_scope_siblings`. `ActionConfig` declared the pair too. The other two carry agent settings and are validated by models with `extra="allow"`, where removing a field refuses nothing on its own, so `manager.py` calls the function directly on each: a legacy top-level `agents:` entry, and the project file's `default_agent_config:` block, which is merged into every agent and is read twice — once for the expander's defaults and once at merge.

Every one of those calls passes all four spellings. Refusing a subset on one surface is this bug again, one spelling over, which is how the second and third of them were found. The boundary is `extra="allow"` itself: those two models accept any undeclared key, so `seed`, the one `context_scope` directive that takes a mapping rather than a list, is refused on the strict surfaces and not on them.

### 3. WorkflowConfig uses `extra="forbid"`

The surface holding the blocks above. It raises the same refusal `DefaultsConfig`
does, over the workflow's own top-level keys, because an undeclared one was dropped
in silence — a `defaluts:` cost every setting in the block at once, and the run that
followed looked healthy.

The same invariant runs the same way, one level up: **every top-level key any
framework code reads out of a workflow file is declared on `WorkflowConfig`**. Two
were not when this was written — `tool_path`, read at `manager.py`, and `storage`,
read at `coordinator.py` through a `getattr` that a grep for `user_config.get` does
not find. `tests/unit/config/test_workflow_keys_read_are_declared.py` walks the AST
and pins the containment; add to both when a module starts reading a new key.

The converse does not hold here either. `storage` is declared and validated, but the
coordinator reads the *raw* dict rather than the validated model, so the block's
validation is a gate at load time and not a guarantee at read time. That is why its
fields are strict: what the model accepts has to be exactly what the raw read
returns. Having consumers read the validated model would remove the need.

### 4. The project config has no model, and is deliberately left that way here

`agent_actions.yml` is read by `load_project_config` as a plain dict, and its keys are
taken with bare `.get()` calls from several sites. A typo there is dropped in silence —
`tool_pth:` falls back to `["tools"]` with no error — which is the same defect the
blocks above refuse, on the file those blocks cross-reference for `tool_path`
precedence. `DefaultAgentConfig`, which one of its keys feeds, is `extra="allow"` and
keeps junk keys for the same reason.

Not an oversight: modelling it is a separate decision, because "declared" has to mean
something different for a file with no model and several independent readers, and
because the merge at `manager.py` mixes it with a block that is already strict. It is
the last remaining instance of this class inside `config/`.

### 5. AgentConfig uses `extra="allow"`

The post-expansion `AgentConfig` (in `output/response/config_schema.py`, not in this module) uses `extra="allow"` because `ActionExpander` injects many runtime-only fields (`agent_type`, `code_path`, `schema_name`, `tools_path`, `is_versioned_agent`, etc.) that aren't in the original YAML. These pass through without Pydantic rejecting them.

### 4. chunk_config gets a shallow deep-merge

In `merge_agent_configs()`, most keys do a flat override (`agent_value wins`). But `chunk_config` is special-cased: `{**default_chunk, **agent_chunk}`. This means per-action chunk_config can override individual sub-keys without losing the rest of the default. However, this is only one level deep — nested sub-keys inside chunk_config are not recursively merged.

### 5. tool_path is always normalized to a list

`tool_path` can be a string or a list in YAML. `ConfigManager.load_configs()` normalizes it to `list[str]` immediately. All downstream code can assume `tool_path` is always a list. When no tool_path is configured anywhere (workflow, default, or project config), it defaults to `["tools"]` with a warning.

### 6. Filename must match the `name` field

`validate_agent_name()` enforces that the workflow's `name` field matches the config file's stem. If your file is `extraction.yml`, the `name:` must be `extraction`. This prevents silent mismatches where a renamed file still loads with the old name.

### 7. Jinja2 rendering happens before YAML parsing

Config files are Jinja2-rendered first via `render_pipeline_with_templates()`, then `yaml.safe_load()`'d. This means you can use Jinja2 syntax in YAML config files (template variables, conditionals, loops). But it also means a Jinja2 syntax error will surface as a `TemplateRenderingError`, not a YAML error.

### 8. Project root search has fallback heuristics

`find_project_root_dir()` first looks for marker files (`agent_actions.yml`, `agent_actions.yaml`, `.agent_actions.yml`). If none are found, it falls back to checking for `agent_actions/` or `agent_config/` directories. When the fallback triggers, a debug log is emitted. This can produce surprising results in monorepos with multiple `agent_config/` directories.

### 9. PathManager cache is CWD-sensitive

When `PathManager` resolves the project root from CWD (no explicit `project_root` argument), it caches both the result and the CWD at resolution time. If CWD changes between calls, the cache is invalidated and re-resolved. When an explicit `project_root` is passed to the constructor, the cache is pinned and never invalidated by CWD changes.

### 10. kind overrides model_vendor at the end

In `get_all_agent_configs_as_dicts()`, after all merging is done, `kind=="tool"` forces `model_vendor="tool"` and `kind=="hitl"` forces `model_vendor="hitl"`. This happens regardless of what `model_vendor` was set to in YAML or defaults. It ensures tool and HITL actions always route to the correct client, even if they inherited `model_vendor: openai` from defaults.

### 11. None fields are coerced to empty strings for downstream safety

`get_all_agent_configs_as_dicts()` converts several `None`-valued optional fields to `""` (or their domain defaults). This prevents downstream code from crashing on `None` where it expects a string (template rendering, conditional checks, etc.). The coerced fields include `conditional_clause`, `granularity`, `run_mode`, `prompt`, `schema_name`, `code_path`, and `anthropic_version`.

### 12. Dependencies are inferred, not just declared

`determine_execution_order()` does not simply read the `dependencies` list from each action. It calls `infer_dependencies()` which analyzes `context_scope` to discover implicit dependencies (e.g., an action that observes fields from another action depends on it). The dependency graph is built from both `input_sources` and `context_sources`. Explicit `dependencies` are only used as a fallback when inference fails.

### 13. Circular dependency detection is iterative, not recursive

The cycle detection in `WorkflowConfig.validate_workflow_invariants()` uses an iterative DFS with explicit stack management (WHITE/GRAY/BLACK coloring). This avoids `RecursionError` on deep dependency chains. When a cycle is detected, the full cycle path is reconstructed from the stack for the error message.

### 14. EnvironmentConfig loads from project root, not CWD

`ConfigManager._resolve_dotenv()` resolves the `.env` file relative to the project root (or `find_project_root_dir()`), not the current working directory. This is important when running the CLI from a subdirectory — it still finds the project's `.env` file.

### 15. ProcessorRegistry is a module-level singleton

`registry = ProcessorRegistry()` at the bottom of `di/container.py` is a module-level singleton. All `@registry.register_*` decorators across the codebase write to this single instance. It is separate from the DI container — the container resolves dependencies by type, while the registry resolves components by name string.

### 16. DI container is thread-safe for singletons only

`DependencyContainer.get()` uses an `RLock` when creating singleton instances (double-check locking pattern). Transient and factory resolutions are not locked. The `_instances` dict can be read without the lock, but writes (first singleton creation) are serialized.

### 17. clean_path refuses to delete outside project root

`PathManager.clean_path()` calls `is_within_project()` before deleting anything. If the path is not under the project root, it raises `ValueError` immediately. This is a safety boundary to prevent accidental deletion of system files. The check depends on `get_project_root()` being resolvable — if the manager was not primed with a root, it will resolve from CWD.

### 18. retry rejects boolean `true` in YAML

Both `ActionConfig` and `DefaultsConfig` have validators that accept `retry: false` (disables) but reject `retry: true` (ambiguous). You must use a mapping like `retry: {max_attempts: 3}`. This prevents users from enabling retry without specifying parameters, which would use defaults they might not be aware of.

### 19. guard expressions are validated at parse time

`ActionConfig.validate_guard()` calls `GuardParser.parse()` (for string guards) or `parse_guard_config()` (for dict guards) during Pydantic validation. Invalid guard expressions fail at config load time, not at runtime when the action executes. This provides early feedback for guard syntax errors.

### 20. seed_data_path rejects path traversal

`get_seed_data_path()` in `path_config.py` rejects any `seed_data_path` containing `..`, `/`, or `\\`. These are interpreted as path traversal attempts and fall back to the default `"seed_data"` with a warning. The `seed_data_path` must be a simple directory name, not a path.
