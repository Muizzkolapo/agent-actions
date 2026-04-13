# Prompt Store Patterns

Guide for writing effective prompts in agent-actions workflows.

## Prompt Structure

```markdown
{prompt Prompt_Name}
[Role/context statement]

[Primary task description]

[Requirements/rules section]

[Output schema]
{end_prompt}
```

## Jinja2 Template Syntax

### Variable Access

```jinja2
{{ seed.exam_syllabus.exam_name }}           # Seed data
{{ source.page_content }}                     # Source document
{{ previous_action.field_name }}              # Upstream action output
```

### Loops

```jinja2
{% for skill in seed.exam_syllabus.skills_measured %}
## {{ skill.skill_area }}
{{ skill.description }}
{% endfor %}
```

### Conditionals

```jinja2
{% if source.code_snippet %}
Review this code:
{{ source.code_snippet }}
{% endif %}
```

## Prompt Reference in YAML

```yaml
prompt: $workflow_name.Prompt_Name
```

## Effective Prompt Patterns

### Pattern 1: Clear Role + Specific Task

```markdown
You are a {{ seed.exam_syllabus.platform_name }} certification exam item-writer
with expertise in creating scenario-based questions.

Your task is to extract atomic, testable facts that help with
implementation, configuration, or troubleshooting.
```

### Pattern 2: Keep/Skip Criteria

```markdown
## Keep
- Config details (params, roles, SKUs)
- Implementation (APIs, SDKs, endpoints)
- Constraints (quotas, limits, regions)

## Skip
- Marketing/benefits
- Generic "can be used to..." statements
- Version numbers without technical impact
```

### Pattern 3: Explicit Output Schema

```markdown
## Output Schema

```json
{
  "question": "string - The scenario question",
  "options": "array[string] - Four plausible choices",
  "answer": "string - Correct answer letter (A, B, C, or D)",
  "answer_explanation": "string - Why the answer is correct"
}
```
```

### Pattern 4: Step-by-Step Process

```markdown
## Generation Steps

1. **Read** the input content carefully
2. **Identify** the core concept being demonstrated
3. **Draft** a scenario that tests understanding
4. **Generate** plausible wrong answers
5. **Verify** the question tests ONE concept only
```

### Pattern 5: Good vs Bad Examples

```markdown
### Good Example
Question tests a specific API method with real-world scenario

### Bad Example
Question defines what a service is (tests memorization, not understanding)
```

## Common Template Variable Errors

### Missing Action Name Prefix

Template variables MUST include the action name prefix when referencing upstream action outputs.

**Wrong:**
```jinja2
{{ summary.word_count }}
{{ items[0] }}
```

**Correct:**
```jinja2
{{ analyze_content.summary.word_count }}
{{ extract_items.items[0] }}
```

**Error you'll see:**
```
PreFlightValidationError: Template references undefined variables
missing_references=['summary']
```

**Rule:** Always use `action_name.field_name` pattern. The action name is the `name:` field from your workflow YAML.

### Accessing Nested Objects

When an action outputs nested objects, chain through the full path:

```jinja2
# Action 'search_catalog' outputs: {results: [...], metadata: {...}}

# Access the array
{% for item in search_catalog.results %}
  {{ item.title }}
{% endfor %}

# Access nested metadata
{{ search_catalog.metadata.total_count }}
```

## Anti-Patterns to Avoid

### Vague Scope

```markdown
# BAD
Extract facts about the platform

# GOOD
Extract atomic, testable facts about {{ seed.exam_syllabus.platform_name }}
that help with implementation, configuration, or troubleshooting
```

### Missing Output Format

```markdown
# BAD
Return the results

# GOOD
Return a JSON object with:
- solution_approach (string): Why this method solves the problem
- key_concept (string): The technical concept being tested
```

### Defining Prerequisites

```markdown
# BAD
SQL is a query language that allows you to...

# GOOD
Use CTEs for complex query optimization in {{ seed.exam_syllabus.platform_name }}
```

## Seed Data Access

Define in workflow defaults:

```yaml
defaults:
  context_scope:
    seed_path:
      exam_syllabus: $file:syllabus.json
```

Access in prompts:

```jinja2
**Exam**: {{ seed.exam_syllabus.exam_name }}

**Target Responsibilities**:
{% for resp in seed.exam_syllabus.audience_profile.responsibilities %}
- {{ resp }}
{% endfor %}
```

## Special Character Handling

```markdown
CRITICAL: Do NOT escape special characters in output.

# WRONG
print(\\"Hello\\")

# RIGHT
print("Hello")
```

## Debugging Prompts

Enable prompt logging:

```yaml
- name: my_action
  prompt: $workflow.My_Prompt
  prompt_debug: true  # Logs rendered prompt
```

## Strict Output Contracts

Prevent LLMs from adding extra fields by being explicit:

```markdown
**STRICT OUTPUT CONTRACT:**
- Return ONLY `questions` array at root level
- Each object has EXACTLY 4 fields: `field_a`, `field_b`, `field_c`, `field_d`
- NO extra fields like `_comments`, `_version`, `metadata`
- NO duplicate representations of the same data
```

Combine with schema `additionalProperties: false`:

```yaml
# schema/my_schema.yml
fields:
  - id: questions
    type: array
    items:
      type: object
      properties:
        question_text: { type: string }
        answer_text: { type: string }
      additionalProperties: false  # Reject extra fields
additionalProperties: false
```

## Model Parameters

### max_tokens

Controls the maximum length of the LLM response. Set this when the default is too short for your output.

```yaml
- name: generate_long_explanation
  max_tokens: 4096                     # Default varies by model
```

| Use case | Suggested range |
|----------|----------------|
| Classification (one word/phrase) | 100-256 |
| Short structured output (3-5 fields) | 512-1024 |
| Long-form generation (paragraphs) | 2048-4096 |
| Complex nested output (arrays of objects) | 2048-4096 |

**Symptom of too-low max_tokens:** Truncated JSON, missing closing braces, incomplete arrays. The response cuts off mid-output, causing JSON parse failures and reprompt loops.

### temperature

Controls randomness. Lower = more deterministic, higher = more creative.

```yaml
- name: classify_issue
  temperature: 0.1                     # Deterministic classification

- name: write_creative_content
  temperature: 0.8                     # Creative variation
```

| Use case | Suggested value |
|----------|----------------|
| Classification, extraction, scoring | 0.0-0.2 |
| Structured analysis, summarization | 0.3-0.5 |
| Content generation, creative writing | 0.6-0.9 |
| Brainstorming, diverse options | 0.9-1.2 |

**Interaction with reprompt:** High temperature + reprompt can help — if the first attempt fails validation, the retry may produce a different (valid) response. Low temperature + reprompt is less effective since retries produce similar output.

**Interaction with versions:** When using `versions` for consensus/voting, moderate temperature (0.4-0.7) ensures each version produces meaningfully different output while staying coherent.

## Best Practices

1. **Start with role & authority** - Establish who the LLM is
2. **Define scope precisely** - Use Keep/Skip filtering criteria
3. **Inject context via templates** - Use `{{ seed.* }}` and `{{ action.* }}`
4. **Show examples** - Both good AND bad examples
5. **Explicit output schema** - Include field types and constraints
6. **Quality gates** - Include tests like "Could this create a question?"
7. **Minimize compound concepts** - Keep scenarios to ONE concept per prompt
8. **Use markdown structure** - Headings, bold, bullets for scannability
9. **Set max_tokens for long output** - Prevent truncation on complex schemas
10. **Match temperature to task** - Low for classification, higher for generation
