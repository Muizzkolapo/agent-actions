# Prompt Field Validation Specification

## Problem Statement

**Current State:**
- Field references in prompts (`{field.path}` or `{{ field.path }}`) are only validated at **runtime**
- Errors occur when processing specific records, not during configuration validation
- No way to detect if a field exists in SOME records but not ALL
- Fragile regex-based parsing fails silently (e.g., with whitespace: `{field }`)
- Poor error messages: "Field 'cluster_name' not found" with no context

**Impact:**
- Workflows fail in production on specific data records
- Hard to debug field reference issues
- No warning about conditional fields that may not exist
- Typos in field names only discovered at runtime

## Solution: Static Prompt Analysis

Validate prompts during `agent-actions validate` to catch issues before runtime.

---

## Architecture

### 1. **Prompt Field Analyzer** (`prompt_field_analyzer.py`)

Extracts and validates field references from prompts.

```python
from agent_actions.validation.prompt_field_analyzer import PromptFieldAnalyzer

analyzer = PromptFieldAnalyzer()

# Extract field references
template = "Extract facts about {{ seed.exam_syllabus.platform_name }}"
refs, syntax = analyzer.extract_field_references(template)

# Validate against available context
available_context = {
    'seed': {'exam_syllabus'},  # Fields available from seed
    'source': {'content', 'url'},  # Source fields
    'flatten_clusters': {'cluster_name', 'grouped_facts'}  # Dependency output
}

issues = analyzer.validate_field_references(refs, available_context)

for issue in issues:
    print(f"{issue.severity}: {issue.message}")
    if issue.suggestion:
        print(f"  Suggestion: {issue.suggestion}")
```

### 2. **Integration Points**

#### A. **Configuration Validation** (`agent-actions validate`)

```python
# In config_validator.py or startup_validator.py

from agent_actions.validation.prompt_field_analyzer import PromptFieldAnalyzer

def validate_workflow_prompts(workflow_config, agent_configs):
    """Validate all prompts in workflow configuration."""
    analyzer = PromptFieldAnalyzer()

    for agent_name, agent_config in agent_configs.items():
        # Get prompt template
        prompt_template = get_prompt_for_agent(agent_config)

        # Extract field references
        refs, syntax = analyzer.extract_field_references(prompt_template, agent_name)

        # Warn about syntax
        if syntax == FieldReferenceType.MIXED:
            logger.error(
                f"Agent '{agent_name}' mixes {{field}} and {{{{field}}}} syntax"
            )
        elif syntax == FieldReferenceType.LEGACY:
            logger.warning(
                f"Agent '{agent_name}' uses legacy {{field}} syntax - "
                f"consider migrating to {{{{field}}}}"
            )

        # Build available context
        dependency_configs = get_dependency_configs(agent_config, agent_configs)
        seed_fields = get_seed_data_fields(agent_config)

        available_context = analyzer.build_available_context(
            agent_config,
            dependency_configs,
            seed_fields
        )

        # Validate field references
        issues = analyzer.validate_field_references(refs, available_context, agent_name)

        # Report issues
        for issue in issues:
            if issue.severity == 'ERROR':
                logger.error(f"[{agent_name}] {issue.message}")
            elif issue.severity == 'WARNING':
                logger.warning(f"[{agent_name}] {issue.message}")
            else:
                logger.info(f"[{agent_name}] {issue.message}")
```

#### B. **Prompt File Validation**

```python
# Validate all prompts in prompt_store/*.md files

from pathlib import Path

prompt_dir = Path("prompt_store")
all_issues = analyzer.analyze_prompt_file(
    prompt_dir / "qanalabs_quiz_gen.md",
    agent_configs=workflow.agent_configs
)

for prompt_name, issues in all_issues.items():
    print(f"\nPrompt: {prompt_name}")
    for issue in issues:
        print(f"  {issue.severity}: Line {issue.field_ref.line_number}")
        print(f"    {issue.message}")
```

### 3. **Validation Rules**

#### Rule 1: Reference Exists
```python
# ERROR: Reference not in available context
"{{ unknown_agent.field }}"
# Available: source, seed, flatten_clusters

# Fix: Add to dependencies or fix typo
dependencies: [unknown_agent]
```

#### Rule 2: Field Exists in Reference
```python
# ERROR: Field not in agent output
"{{ flatten_clusters.cluster_name }}"
# Available fields: grouped_facts, num_similar_facts

# Fix: Check output schema or add to passthrough
```

#### Rule 3: Nested Field Warning
```python
# WARNING: Can't validate deeply nested
"{{ seed.exam_syllabus.platform_name }}"

# Suggestion: Verify exam_syllabus has platform_name
```

#### Rule 4: Conditional Field Warning
```python
# WARNING: Field may not always exist
"{{ flatten_clusters.cluster_name }}"  # Only exists when should_keep_cluster=false

# Suggestion: Add guard condition
guard:
  condition: 'cluster_name != None'
  on_false: "skip"
```

---

## Usage Examples

### Example 1: Basic Validation

**Prompt:**
```markdown
{prompt Fact_extraction}
Extract facts about {{ seed.exam_syllabus.platform_name }}

Source: {{ source.content }}
{end_prompt}
```

**Validation:**
```python
analyzer = PromptFieldAnalyzer()
refs, syntax = analyzer.extract_field_references(prompt_content)

# Found references:
# - seed.exam_syllabus.platform_name (line 2)
# - source.content (line 4)

available = {
    'seed': {'exam_syllabus'},
    'source': {'content', 'url'}
}

issues = analyzer.validate_field_references(refs, available)
# Result: 1 WARNING - nested field seed.exam_syllabus.platform_name
```

### Example 2: Detect Missing Fields

**Prompt:**
```markdown
{prompt Summary_Generator}
Cluster: {{ flatten_clusters.cluster_name }}
Facts: {{ flatten_clusters.grouped_facts }}
{end_prompt}
```

**Validation:**
```python
available = {
    'flatten_clusters': {'grouped_facts', 'num_similar_facts'}
    # Note: cluster_name missing!
}

issues = analyzer.validate_field_references(refs, available)
# Result: ERROR - Field 'cluster_name' not found in 'flatten_clusters'
#         Available fields: grouped_facts, num_similar_facts
#         Suggestion: Check output schema or add to passthrough
```

### Example 3: Mixed Syntax Detection

**Prompt:**
```markdown
{prompt Bad_Example}
Legacy: {source.content}
Jinja2: {{ source.url }}
{end_prompt}
```

**Validation:**
```python
refs, syntax = analyzer.extract_field_references(prompt_content)
# syntax = FieldReferenceType.MIXED

# ERROR: Prompt mixes legacy {field} and Jinja2 {{ field }} syntax
#        Please use only one syntax
```

---

## CLI Output

When running `agent-actions validate`:

```bash
$ agent-actions validate

Validating workflow configuration...
✓ Config structure valid
✓ Schema definitions valid
✓ Prompt files found

Analyzing prompt field references...

Agent: fact_extractor
  ✓ Prompt uses Jinja2 syntax (recommended)
  ✓ All field references valid

Agent: generate_summary
  ⚠️  WARNING [Line 2]: Nested field 'flatten_clusters.content.cluster_name'
      cannot be fully validated
      → Verify 'content' object has 'cluster_name' field

  ❌ ERROR [Line 5]: Field 'cluster_name' not found in 'flatten_clusters'
      Available fields: grouped_facts, num_similar_facts
      → Check output schema of 'flatten_clusters'
      → Or add 'cluster_name' to context_scope.passthrough

  💡 SUGGESTION: Add guard condition to handle missing 'cluster_name':
      guard:
        condition: 'cluster_name != None'
        on_false: "skip"

Validation failed with 1 error, 1 warning
```

---

## Benefits

1. **Catch Errors Early**: Find field issues during `validate`, not in production
2. **Better Error Messages**: Show line numbers, available fields, suggestions
3. **Migration Support**: Detect legacy `{field}` vs Jinja2 `{{ field }}` syntax
4. **Conditional Field Detection**: Warn about fields that may not always exist
5. **Auto-Fix Suggestions**: Provide actionable fixes for common issues

---

## Implementation Checklist

- [x] Create `PromptFieldAnalyzer` class
- [ ] Integrate into `agent-actions validate` command
- [ ] Add to `PromptValidator.validate()` flow
- [ ] Create tests for all validation rules
- [ ] Add CLI output formatting
- [ ] Document in user guide
- [ ] Add to CI/CD validation pipeline

---

## Future Enhancements

1. **Schema-Aware Validation**: Load JSON schemas to validate nested field paths
2. **Auto-Fix Tool**: `agent-actions fix-prompts` to auto-convert legacy syntax
3. **IDE Integration**: VS Code extension to show errors inline
4. **Conditional Analysis**: Detect when guards protect field references
5. **Field Usage Report**: Show which fields are used where across workflow
