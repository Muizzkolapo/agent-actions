# Prompt Module Architecture

This document maps the moving parts of `agent_actions/prompt/` -- the module that transforms raw prompt templates and record data into the final `messages[]` array sent to LLM providers.

---

## High-Level Overview

```
                        agent_actions/prompt/
                              |
              +---------------+---------------+
              |                               |
        PREPARATION LAYER               ASSEMBLY LAYER
       (template + context)           (provider messages)
              |                               |
  +-----------+-----------+          +--------+--------+
  |           |           |          |                 |
service.py  handler.py  context/   message_builder.py |
(orchestrate) (load .md) (scope)   (per-vendor msgs)  |
  |           |           |          |                 |
formatter.py  |   scope_builder.py   +--- LLMMessage   |
(resolve $)   |   scope_application  |    Envelope     |
              |   scope_inference    |                 |
              |   null_namespace     |                 |
              |   static_loader      |                 |
              |   scope_parsing      |                 |
              |                      |                 |
     render_workflow.py         renderer.py      prompt_utils.py
     (compile YAML configs)   (CLI rendering)   (dispatch_task)
```

The module has **two layers**:

| Layer | What it does |
|-------|-------------|
| **Preparation** | Resolves the raw prompt template, builds the field context from upstream actions and seed data, applies context_scope (observe/drop/passthrough), renders Jinja2, and resolves `dispatch_task()` calls. Output: a rendered prompt string + filtered LLM context dict + passthrough fields. |
| **Assembly** | Takes the rendered prompt and LLM context from the preparation layer and assembles the vendor-specific `messages[]` array (system/user roles, tagged formatting, schema injection). Output: `LLMMessageEnvelope` ready for the provider SDK. |

---

## Prompt Template Resolution

Prompts can be defined in two ways:

```
INLINE (in agent_config YAML):
  prompt: "Summarize the following text: {{ source.text }}"

FILE REFERENCE (from prompt_store/*.md):
  prompt: "$summarize.main_prompt"
          ^       ^
          |       +-- block name inside the .md file
          +-- filename (prompt_store/summarize.md)
```

Resolution flow:

```
PromptFormatter.get_raw_prompt(agent_config)
  |
  +-- prompt starts with "$"?
  |     YES --> PromptLoader.load_prompt("summarize.main_prompt")
  |               1. Split on first dot: file="summarize", block="main_prompt"
  |               2. Find prompt_store/summarize.md recursively
  |               3. Extract text between {prompt main_prompt} and {end_prompt}
  |               4. Validate: no duplicate blocks, all blocks closed
  |     NO  --> Use string as-is
  |
  +-- prompt missing entirely?
  |     --> Default: "Process the following content: {content}"
  |
  +-- prompt is empty/whitespace (non-tool action)?
        --> ConfigValidationError
```

---

## Context Scope System (Security-Critical)

`context_scope` is the security boundary that controls what data the LLM sees in its prompt and what data appears in its output. Every action must declare one.

```
context_scope:
  observe:      ["extract.title", "extract.body"]
  passthrough:  ["source.customer_id"]
  drop:         ["source.ssn", "source.salary"]
  seed:
    rules: "grading_rubric.json"
```

### The three directives

| Directive | LLM sees it? | Output gets it? | Purpose |
|-----------|-------------|-----------------|---------|
| `observe` | YES (in prompt context + "Additional context" injection) | NO (unless also in passthrough) | Feed data to the LLM for reasoning |
| `passthrough` | NO (not in LLM context) | YES (merged into output record) | Carry identifiers through without LLM exposure |
| `drop` | NO | NO | **Remove from BOTH input AND output** |

### Drop wins over passthrough

Drop is applied **after** passthrough extraction. If a field appears in both `passthrough` and `drop`, it is removed from the passthrough dict. This is intentional: drop is the security override.

```
Processing order inside apply_context_scope():

  1. Deep-copy field_context (never mutate original)
  2. Add seed data under "seed" namespace
  3. Extract PASSTHROUGH fields from pre-drop context
  4. Apply DROP: remove from prompt_context AND passthrough_fields
  5. Extract OBSERVE fields to llm_context (kept in prompt_context too)
  6. GATE prompt_context: only observed/passthrough namespaces + FRAMEWORK_NAMESPACES
```

### Visual example

```
Input Record:
  {name: "Alice", age: 30, ssn: "123-45-6789", dept: "Eng", salary: 90000}

context_scope:
  drop: [source.ssn, source.salary]
  observe: [source.dept]
  passthrough: [source.name]

                    +--- What the LLM prompt gets ---+
                    | {name: "Alice", age: 30,       |
                    |  dept: "Eng"}                   |
                    | (ssn and salary dropped)        |
                    |                                 |
                    | Additional context:             |
                    |   source.dept: "Eng"            |
                    +---------------------------------+

                    +--- What the OUTPUT gets --------+
                    | {<llm_output>, name: "Alice"}   |
                    | (passthrough merged, LLM wins   |
                    |  on key collision)               |
                    +---------------------------------+
```

---

## Field Context Namespace Anatomy

`build_field_context_with_history()` assembles the field context from four composable namespace builders:

```
field_context = {
    "source":     {...},    # Namespace 1: Original input data (SourceNamespaceBuilder)
    "{dep_name}": {...},    # Namespace 2: Upstream action outputs (DependencyNamespaceBuilder)
    "seed":       {...},    # Namespace 3: Static reference data (added by apply_context_scope)
    "version":    {...},    # Namespace 4: Loop iteration info (VersionNamespaceBuilder)
    "workflow":   {...},    # Namespace 5: Workflow metadata (WorkflowMetadataBuilder)
}
```

| Namespace | Builder | Source | Template access |
|-----------|---------|--------|-----------------|
| `source` | `SourceNamespaceBuilder` | User input data from staging | `{{ source.text }}` |
| `{dep_name}` | `DependencyNamespaceBuilder` | Output of upstream action(s) | `{{ extract.title }}` |
| `seed` | Added in `apply_context_scope` | Static files from `seed_data/` | `{{ seed.rubric }}` |
| `version` | `VersionNamespaceBuilder` | Loop iteration context (`i`, `idx`, `length`, `first`, `last`) | `{{ version.i }}` or `{{ i }}` |
| `workflow` | `WorkflowMetadataBuilder` | Workflow-level metadata | `{{ workflow.name }}` |

Version and workflow convenience: `i`, `idx`, and custom version params are promoted to top-level so `{{ i }}` works alongside `{{ version.i }}`.

---

## NullNamespace Sentinel

When a guard skips or filters an upstream action, the downstream record has `{action_name: None}` in its content. The `DependencyNamespaceBuilder` wraps this in a `NullNamespace` sentinel so downstream code can distinguish three cases:

```
1. NullNamespace(reason="skipped")  --> Namespace declared but absent (guard-skipped)
2. Dict with fields                 --> Normal namespace with data
3. Key absent from field_context    --> Undeclared namespace (config bug / typo --> error)
```

`is_null_namespace(value)` returns True for both `NullNamespace` instances and legacy `None` values. This is used by:
- `apply_context_scope` -- resolves observe/passthrough fields to `None` instead of crashing
- `_render_prompt_template` -- blames the dereferenced null namespace in the render error and attaches remediation hints
- Guard evaluator AST nodes -- null-safe field access

---

## Jinja2 Rendering Pipeline

```
_render_prompt_template(raw_prompt, prompt_context)
  |
  1. If prompt_context is empty --> return raw_prompt unchanged
  |
  2. Create Environment(undefined=StrictUndefined,
  |                     finalize=lambda x: "" if x is None else x)
  |
  3. escape_jinja_in_inline_code(raw_prompt)
  |     Escapes {{ }} inside code fences so they are not interpreted
  |
  4. template.render(**prompt_context)
  |     |
  |     +-- UndefinedError --> Raise TemplateVariableError with diagnostics:
  |           |                - namespace_context (available refs per namespace)
  |           |                - storage_hints (field exists in DB but not loaded)
  |           |                - null_namespace_hints (guard-skipped/filtered dep
  |           |                  advice; fires whenever a null namespace is in
  |           |                  scope and the template dereferenced it)
  |
  5. Return rendered string
```

**StrictUndefined** means typos in template references fail loudly rather than silently rendering empty. Dereferencing a guard-skipped namespace is no exception: it raises, but the error carries `null_namespace_hints` naming the namespace and the remediation (`ns.*` null-safe access, or a guard on the consuming action).

---

## Complete Prompt Preparation Pipeline

`PromptPreparationService.prepare_prompt_with_context()` is the single source of truth for prompt preparation. Both batch and online modes call it.

```
Step 1: LOAD RAW PROMPT
  PromptFormatter.get_raw_prompt(agent_config)
  --> inline string or $file.block reference resolved
  
Step 2: BUILD FIELD CONTEXT
  build_field_context_with_history(...)
  --> Assembles {source, deps, version, workflow} namespaces
  --> Pops _dependency_metadata for diagnostic use later
  
Step 3: LOAD SEED DATA
  StaticDataLoader.load_static_data(seed_config)
  --> Loads JSON/YAML/CSV/text files from seed_data/ directory
  --> Returns dict keyed by field_name from config
  
Step 4: APPLY CONTEXT SCOPE
  apply_context_scope(field_context, context_scope, static_data)
  --> Returns (prompt_context, llm_additional_context, passthrough_fields)
  --> Deep-copies input, applies drop/observe/passthrough, gates prompt_context
  
Step 5: BUILD LLM CONTEXT
  LLMContextBuilder.build_llm_context_for_{batch|online}(...)
  --> Merges observe fields into base context
  --> Applies seed drop rules
  
Step 6: RENDER JINJA2 TEMPLATE
  _render_prompt_template(raw_prompt, prompt_context)
  --> Jinja2 with StrictUndefined; bare null namespace renders empty,
  |       field access on one raises with remediation hints
  --> Produces formatted_prompt string
  
Step 7: RESOLVE DISPATCH_TASK() CALLS
  PromptUtils.inject_function_outputs_into_prompt(...)
  --> Finds dispatch_task('function_name') patterns in rendered prompt
  --> Calls user Python functions from tools/ directory
  --> Replaces pattern with function return value
  --> Runs AFTER Jinja2 so dispatch sees the rendered prompt
```

---

## MessageBuilder and Provider Message Configs

After the preparation layer produces a rendered prompt and LLM context, provider clients call `MessageBuilder.build()` to assemble the vendor-specific `messages[]` array.

```
MessageBuilder.build(provider, prompt, context, schema, json_mode, ...)
  |
  1. Look up PROVIDER_MESSAGE_CONFIGS[provider]
  |     --> ProviderMessageConfig(json_prompt_style, non_json_prompt_style,
  |         json_role, non_json_role, schema_injection, json_rules, ...)
  |
  2. Serialise context to string
  |     --> dict -> str(ensure_json_safe(data))  (most providers)
  |     --> dict -> json.dumps(data)             (ollama)
  |
  3. Assemble body (based on PromptStyle)
  |     TAGGED      --> <|begin_of_user_instruction|>: {prompt} :<|end|>
  |                     <|begin_of_text|>: {context} :<|end|>
  |     TAGGED_GROQ --> Same tags, different colon/spacing convention
  |     PLAIN_TEXT  --> "Instructions: ... / Input Text: ..."
  |     RAW         --> Empty (roles handle separation)
  |
  4. Inject schema (based on SchemaInjection)
  |     NONE            --> Schema passed via API param (OpenAI, Anthropic)
  |     INLINE_FULL     --> <|begin_of_output_schema|> : {schema}
  |     INLINE_FULL_LIST--> list of this [{schema}] (Gemini)
  |     INLINE_FIELDS   --> Field names only (Cohere)
  |     PROMPT          --> Schema appended to prompt text (Ollama Cloud)
  |
  5. Wrap in roles (based on MessageRole)
  |     SINGLE_USER      --> [{role: "user", content: body}]
  |     SYSTEM_PLUS_USER --> [{role: "system", content: prompt},
  |                          {role: "user", content: context}]
  |     SYSTEM_ONLY      --> [{role: "system", content: body}]
  |       (TAGGED + context --> splits into system + user for injection safety)
  |
  6. Anthropic prompt caching
  |     --> Adds cache_control: {type: "ephemeral"} to messages
  |
  7. Token overflow pre-flight
  |     --> chars/4 heuristic vs _MODEL_CONTEXT_LIMITS
  |     --> PromptTooLargeError if exceeded
  |
  --> Returns LLMMessageEnvelope(messages, prompt_body, rules)
```

### Provider configuration matrix

| Provider | JSON Style | Non-JSON Style | JSON Role | Schema Injection | Special Rules |
|----------|-----------|----------------|-----------|------------------|---------------|
| `openai` | TAGGED | TAGGED | SYSTEM_ONLY | NONE | "CANNOT RETURN SCHEMA", "READ INPUT AS STRING" |
| `anthropic` | TAGGED | TAGGED | SINGLE_USER | NONE | (none) |
| `gemini` | TAGGED | TAGGED | SINGLE_USER | INLINE_FULL_LIST | "DO NOT ADD KEY NOT IN SCHEMA" |
| `groq` | TAGGED_GROQ | PLAIN_TEXT | SYSTEM_ONLY | NONE | "Respond in valid JSON" |
| `cohere` | TAGGED | TAGGED | SINGLE_USER | INLINE_FIELDS | "CANNOT RETURN SCHEMA" |
| `ollama_local` | RAW | RAW | SYSTEM_PLUS_USER | NONE | (none) |
| `ollama_cloud` | RAW | RAW | SYSTEM_PLUS_USER | PROMPT | (none) |

---

## Seed Data Loading

`StaticDataLoader` loads reference data from the `seed_data/` directory for injection into prompts via the `seed` namespace.

```
context_scope:
  seed:
    rubric: "grading_rubric.json"
    examples: "few_shot_examples.yml"

StaticDataLoader(static_data_dir=Path("seed_data/"))
  .load_static_data({"rubric": "grading_rubric.json", ...})
    |
    For each field_name, file_spec:
      1. Parse path: strip "$file:" prefix if present
      2. Resolve path relative to seed_data/ directory
      3. SECURITY: reject absolute paths, reject path traversal (../../etc/passwd)
         --> Delegates to resolve_seed_path() which validates resolved path
             stays within static_data_dir
      4. Check file size (configurable max, prevents memory exhaustion)
      5. Load by extension:
           .json --> json.load()
           .yml/.yaml --> yaml.safe_load()
           .md/.txt --> raw text string
           .csv --> list of dicts (DictReader)
      6. Cache by resolved path (in-memory, per-loader instance)
    |
    Returns: {"rubric": {...}, "examples": [...]}
    --> Merged into prompt_context["seed"] by apply_context_scope
```

---

## Workflow Rendering Pipeline

`render_pipeline_with_templates()` compiles a workflow YAML into a self-contained configuration. This runs at workflow load time, before any records are processed.

```
render_pipeline_with_templates(yaml_path, templates_folder)
  |
  Step 1: Jinja2 template rendering (workflow-level macros and includes)
  Step 2: Parse YAML
  Step 3: Resolve prompt references ($file.block --> inline text)
  Step 4: Expand versioned actions (versions: {param: i, range: [1,3]})
  Step 5: Compile schemas (schema_name: "foo" --> inline schema from file)
  |
  --> Fully self-contained YAML string
```

---

## File Index

### Core orchestration
| File | Role |
|------|------|
| `service.py` | `PromptPreparationService` -- single source of truth for prompt preparation (both batch and online). Orchestrates all 7 pipeline steps. |
| `formatter.py` | `PromptFormatter` -- resolves raw prompt from agent_config (inline or `$file.block` reference). |
| `handler.py` | `PromptLoader` -- loads and validates prompts from `prompt_store/*.md` files. Extracts named blocks, validates uniqueness and closure. |
| `message_builder.py` | `MessageBuilder` -- assembles vendor-specific `LLMMessageEnvelope` from prompt + context. `PROVIDER_MESSAGE_CONFIGS` registry. |

### Context scope (security-critical)
| File | Role |
|------|------|
| `context/scope_application.py` | `apply_context_scope()` -- the security gate. Observe/drop/passthrough filtering, prompt_context gating, FILE mode variant. |
| `context/scope_builder.py` | `build_field_context_with_history()` -- assembles field_context from 4 namespace builders: source, dependency, version, workflow. |
| `context/scope_inference.py` | `infer_dependencies()` -- auto-infers input/context sources from action config, fan-in detection, version branch expansion. |
| `context/scope_parsing.py` | `parse_field_reference()` -- parses "action.field" references. `extract_action_names_from_template()` -- AST-based Jinja2 dependency extraction. |
| `context/scope_namespace.py` | Namespace enrichment, field filtering, allowed-fields-per-dependency extraction. |
| `context/null_namespace.py` | `NullNamespace` sentinel and `is_null_namespace()` for guard-skipped/filtered upstream actions. |
| `context/static_loader.py` | `StaticDataLoader` -- loads seed data files (JSON, YAML, CSV, text) with path traversal prevention and caching. |
| `context/builder.py` | `LLMContextBuilder` -- merges observe fields into LLM context, applies seed drop rules. Shared implementation for batch and online. |

### Rendering and utilities
| File | Role |
|------|------|
| `render_workflow.py` | `render_pipeline_with_templates()` -- compiles workflow YAML (Jinja2 macros, prompt resolution, schema inlining, version expansion). |
| `renderer.py` | `JinjaTemplateRenderer` + `ConfigRenderingService` -- CLI/validation entry points for config rendering and loading. |
| `prompt_utils.py` | `PromptUtils` -- `dispatch_task()` resolution, field reference parsing and replacement. |
| `data_generator.py` | `DataGenerator` -- composes prompt preparation with `OnlineLLMStrategy` for the generate CLI command. |

---

## Caveats

1. **context_scope is a security boundary.** It controls what the LLM sees and what appears in output. A misconfigured scope can leak PII (missing drop) or silently lose data (over-aggressive drop). Every action must declare one; omitting it raises `ConfigurationError`.

2. **apply_context_scope deep-copies field_context.** The original input dict is never mutated. This is load-bearing: the same field_context may be reused across records in FILE mode, and mutation would corrupt subsequent records.

3. **PromptPreparationService is the single source of truth.** Both batch (`TaskPreparer`) and online (`OnlineLLMStrategy`) must call `prepare_prompt_with_context()`. Adding mode-specific context logic elsewhere creates context parity bugs where batch and online produce different prompts for the same record.

4. **The context gate is easy to break.** After observe/drop/passthrough processing, `apply_context_scope` gates `prompt_context` to only scoped namespaces plus `FRAMEWORK_NAMESPACES`. If you add a new framework namespace (like `loop` was added alongside `version`, `seed`, `workflow`), you must add it to `FRAMEWORK_NAMESPACES` in `scope_application.py` or it will be filtered out of templates.

5. **NullNamespace is not None.** `NullNamespace(reason="skipped")` is a sentinel that is falsy (so `if ns_data:` skips it) but is not `None`. Use `is_null_namespace(value)` to check for either. Code that checks `value is None` will miss `NullNamespace` instances and crash. Code that checks `not value` will catch both but also catch empty dicts -- which have different semantics.

6. **FRAMEWORK_NAMESPACES bypass the context gate.** The namespaces `version`, `seed`, `workflow`, and `loop` are always available for Jinja2 template rendering regardless of what is declared in observe/passthrough. They are not user data -- they are iteration context and metadata. Adding user-data namespaces to this set would create a security bypass.

7. **Schema metadata stripping prevents schema-echo.** `MessageBuilder._strip_schema_metadata()` removes `name`, `title`, and `description` keys before injecting schemas into prompt text (for providers using `INLINE_FULL`, `INLINE_FULL_LIST`, or `PROMPT` injection). Without this, models return the schema definition itself instead of conforming data. This only affects prompt-injected schemas -- providers with native structured output (OpenAI, Anthropic) pass the full schema via API parameters.

8. **dispatch_task() runs after Jinja2 rendering.** The resolution order is: Jinja2 template render first (step 6), then `dispatch_task()` resolution (step 7). This means `dispatch_task()` calls see the fully rendered prompt with all template variables resolved. User functions receive the LLM context as a JSON string argument.

9. **StrictUndefined has no exceptions.** Jinja2 uses `StrictUndefined` so typos in template references fail loudly. Dereferencing a guard-skipped namespace fails loudly too — silently rendering `""` would send a half-empty prompt to the provider. The failure is made actionable instead: `null_namespace_hints` names the null namespace the template touched, lists the non-null namespaces available, and points at `ns.*` null-safe access or a guard on the consuming action.

10. **Drop order matters for passthrough.** Passthrough fields are extracted from the pre-drop prompt_context, then drop is applied to both prompt_context and passthrough_fields. This means passthrough captures the value before drop, but drop still removes it. If the order were reversed (drop then passthrough), passthrough would never see the field. The current order ensures drop is the final authority.

11. **Seed data path traversal prevention is delegated.** `StaticDataLoader._resolve_path()` delegates to `resolve_seed_path()` from `utils/path_security.py`. This validates that the resolved path stays within `static_data_dir` after symlink resolution. The loader also rejects absolute paths as a first-pass check before delegation.

12. **Token overflow is a heuristic.** `MessageBuilder` estimates tokens as `total_chars / 4` and compares against `_MODEL_CONTEXT_LIMITS`. This is within approximately 20% of actual tokenization for English text. The check raises `PromptTooLargeError` before the API call, saving latency and cost. Models not in the lookup table fall back to 128K tokens.
