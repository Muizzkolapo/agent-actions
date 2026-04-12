# Cross-Workflow Patterns

How to chain workflows so one workflow's output feeds into another.

## How It Works

Workflows can declare dependencies on actions in other workflows via manifest linking. The framework resolves cross-workflow references at runtime using the workspace index and dependency graph.

## Configuration

```yaml
# Upstream workflow: qanalabs_quiz_gen/agent_config/qanalabs_quiz_gen.yml
actions:
  - name: format_quiz_text    # Last action — output consumed downstream
    # ...

# Downstream workflow: run_thinkific_gen/agent_config/run_thinkific_gen.yml
actions:
  - name: fix_code_snippets
    dependencies:
      - workflow: qanalabs_quiz_gen
        action: format_quiz_text
    context_scope:
      observe:
        - format_quiz_text.*   # Resolved via manifest, not within-workflow lookup
```

Cross-workflow dependencies use dict syntax (`{workflow: name, action: action_name}`) instead of string syntax. The `action` field is optional — omit it to depend on the entire upstream workflow's terminal output.

## Running

```bash
# Run the upstream workflow first, then downstream
agac run -a qanalabs_quiz_gen --downstream

# Or run just the downstream (assumes upstream output already exists)
agac run -a run_thinkific_gen --upstream
```

`--downstream` triggers all workflows that depend on the current one. `--upstream` runs all dependencies before the target.

## Observe and Context Scope

Cross-workflow observe references work the same as within-workflow:

```yaml
context_scope:
  observe:
    - format_quiz_text.*           # All fields from upstream action
    - format_quiz_text.quiz_html   # Specific field
  passthrough:
    - format_quiz_text.quiz_id     # Forward without LLM seeing it
```

The action name is the key — not the workflow name. If the upstream action is `format_quiz_text`, you observe `format_quiz_text.*` regardless of which workflow it belongs to.

## Common Mistakes

### Using impl name instead of action name

Use the `name:` field from the YAML, not the `impl:` function name. See contract #20 in **[Common Pitfalls](common-pitfalls.md)**.

### Missing context_scope for cross-workflow fields

```yaml
# WRONG — dependency declared but no observe
- name: process_upstream
  dependencies:
    - workflow: upstream_workflow
      action: final_action
  context_scope:
    observe:
      - source.*   # Only observes source, not upstream!

# CORRECT — observe the cross-workflow action's fields
- name: process_upstream
  dependencies:
    - workflow: upstream_workflow
      action: final_action
  context_scope:
    observe:
      - final_action.*
```

## Known Limitations

1. **Static checker skips cross-workflow validation.** The static analyzer accepts the dependency syntax but does not validate that observed fields exist in the upstream workflow. Field reference errors surface at runtime, not at `agac validate` time. A fix is in progress.

2. **No cross-workflow guard references.** Guard conditions can only reference fields from within-workflow actions. You cannot guard on a field produced by an upstream workflow's action directly — use a tool action to extract and expose the field first.

3. **Workspace index required.** Cross-workflow resolution requires a valid `agent_actions.yml` with all workflows registered. If a workflow is missing from the project config, the dependency silently fails to resolve.
