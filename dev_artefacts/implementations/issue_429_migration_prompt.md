# Migration Prompt: Transition to {reference.field} Pattern

## For Claude Code or Developers

Use this prompt to migrate existing workflow YAML files from old patterns to new `{reference.field}` syntax.

---

**Prompt:**

```
I need to migrate my agent workflow YAML files to use the new {reference.field} pattern.

Please scan all YAML files in the project and update prompts to use the new syntax:

OLD PATTERNS → NEW PATTERNS:

1. source_context{{['field']}} → {source.field}
   Example: source_context{{['page_content']}} → {source.page_content}

2. source_context{{}} → {source.field} (when referencing specific fields)
   Example: "Process source_context{{}}" → "Process {source.content}"

3. return_collection[field] → {agent_name.field}
   Example: return_collection[metrics] → {extractor.metrics}
   Note: You need to identify which dependency agent owns the field

AVAILABLE REFERENCE TYPES:
- {source.field} - Original workflow input
- {agent_name.field} - Output from dependency agent (check depends_on)
- {agent.nested.field} - Nested field access
- {loop.index}, {loop.total}, {loop.item.field} - Loop context
- {workflow.name}, {workflow.version}, {workflow.run_id} - Workflow metadata

RULES:
1. For return_collection[field], check the agent's depends_on to identify the correct agent name
2. Replace all occurrences in the prompt field
3. Preserve all other YAML structure
4. If unsure which agent owns a field, flag it for manual review

Please update all files and show me the changes.
```

---

## Example Migration

**Before:**
```yaml
agents:
  analyzer:
    prompt: |
      Analyze this content: source_context{{['page_content']}}
      Use these metrics: return_collection[metrics]
      Previous summary: return_collection[summary]
    depends_on:
      - extractor
      - classifier
```

**After:**
```yaml
agents:
  analyzer:
    prompt: |
      Analyze this content: {source.page_content}
      Use these metrics: {extractor.metrics}
      Previous summary: {classifier.summary}
    depends_on:
      - extractor
      - classifier
```

## Quick Reference

| Old Pattern | New Pattern | Example |
|-------------|-------------|---------|
| `source_context{{['field']}}` | `{source.field}` | `{source.page_content}` |
| `return_collection[field]` | `{agent.field}` | `{extractor.metrics}` |
| N/A | `{agent.nested.field}` | `{extractor.data.count}` |
| N/A | `{loop.index}` | In loop agents |
| N/A | `{workflow.name}` | Workflow metadata |
