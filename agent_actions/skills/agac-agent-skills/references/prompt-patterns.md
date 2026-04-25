# Prompt Patterns

## Structure

```markdown
{prompt Prompt_Name}
[Role statement]
[Task]
[Rules / Keep-Skip criteria]
[Output schema]
{end_prompt}
```

Reference: `prompt: $workflow_name.Prompt_Name`

## Jinja2 Syntax

```jinja2
{{ seed.exam_syllabus.exam_name }}           # Seed data
{{ source.page_content }}                     # Source document
{{ previous_action.field_name }}              # Upstream output

{% for skill in seed.exam_syllabus.skills_measured %}
## {{ skill.skill_area }}
{% endfor %}

{% if source.code_snippet %}
Review this code: {{ source.code_snippet }}
{% endif %}
```

## Variable Rules

**Always prefix with action name** when referencing upstream output:

```jinja2
{{ analyze_content.summary.word_count }}     # Correct
{{ summary.word_count }}                      # Wrong -- PreFlightValidationError
```

Nested access chains through full path: `{{ search_catalog.metadata.total_count }}`

## Seed Data

Config:

```yaml
defaults:
  context_scope:
    seed_path:
      exam_syllabus: $file:syllabus.json
```

Access: `{{ seed.exam_syllabus.exam_name }}`. Config key is `seed_path:`, runtime prefix is `seed.` (not `seed_data.`).

## Model Parameters

| Parameter | Use case | Range |
|-----------|----------|-------|
| `max_tokens` | Classification | 100-256 |
| | Short structured (3-5 fields) | 512-1024 |
| | Long-form / complex nested | 2048-4096 |
| `temperature` | Classification, extraction | 0.0-0.2 |
| | Analysis, summarization | 0.3-0.5 |
| | Content generation | 0.6-0.9 |
| | Brainstorming | 0.9-1.2 |

**Gotchas:**
- Too-low `max_tokens` = truncated JSON, missing braces, reprompt loops.
- High temp + reprompt = good (retries differ). Low temp + reprompt = bad (retries repeat).
- Versions for consensus: use moderate temp (0.4-0.7) so versions meaningfully differ.

## Strict Output Contract

Prevent extra fields from LLM:

```markdown
**STRICT OUTPUT CONTRACT:**
- Return ONLY `questions` array at root level
- Each object has EXACTLY 4 fields: `field_a`, `field_b`, `field_c`, `field_d`
- NO extra fields like `_comments`, `_version`, `metadata`
```

Combine with `additionalProperties: false` in schema.

## Special Characters

Tell LLM not to escape:

```markdown
CRITICAL: Do NOT escape special characters in output.
# WRONG: print(\\"Hello\\")
# RIGHT: print("Hello")
```

## Debugging

```yaml
- name: my_action
  prompt: $workflow.My_Prompt
  prompt_debug: true          # Logs rendered prompt
```

## Anti-Patterns

| Bad | Good |
|-----|------|
| "Extract facts about the platform" | "Extract atomic, testable facts about {{ seed.exam_syllabus.platform_name }} for implementation, configuration, or troubleshooting" |
| "Return the results" | "Return JSON with: `solution_approach` (string), `key_concept` (string)" |
| Defining prerequisites the LLM knows | Specific task with injected context |
