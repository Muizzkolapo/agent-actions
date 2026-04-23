# HITL Patterns

Human-in-the-loop (HITL) actions pause the pipeline and wait for human input via a local web UI. Use HITL when automated output needs human review, correction, or approval before downstream processing.

## Basic HITL

The simplest pattern: pause for human review, then continue.

```yaml
- name: review_output
  kind: hitl
  granularity: file              # Default for HITL — can be omitted
  hitl:
    port: 8501                   # Local web UI port
    timeout: 3600                # Seconds to wait (default: 1 hour)
  dependencies: [generate_draft]
  context_scope:
    observe: [generate_draft.*]
```

The web UI presents all records for review. The human can edit field values, approve, or reject records. When the session completes, the pipeline resumes with the human-modified data.

HITL defaults to `granularity: file` (operates on the full file). Setting `granularity: record` will error.

## HITL with Guard Pre-Filter

Filter records before presenting them to the human. Only records matching the guard condition appear in the review UI.

```yaml
- name: auto_review_quality
  dependencies: [score_quality]
  schema: { decision: string, confidence: number, reasoning: string }
  prompt: $workflow.Auto_Review
  context_scope:
    observe: [score_quality.*]

- name: human_review
  kind: hitl
  granularity: file
  hitl:
    port: 8501
    timeout: 3600
  dependencies: [auto_review_quality]
  guard:
    condition: 'auto_review_quality.decision == "review"'
    on_false: "skip"             # Approved records skip human review
  context_scope:
    observe: [auto_review_quality.*]
    passthrough:
      - score_quality.*          # Forward scores for context in UI
```

This pattern reduces human workload: the LLM auto-approves clear cases, and only ambiguous records go to the human.

**How guard evaluation works with HITL:**
1. Guard evaluates on the full file of records (pre-filter phase)
2. Only records where the condition is true are presented in the HITL UI
3. Records where the condition is false are passed through with `on_false` behavior (`skip` = continue without review, `filter` = remove)

## HITL + Downstream Actions

When downstream actions depend on HITL output, use passthrough to preserve data through the review step.

```yaml
- name: human_review
  kind: hitl
  granularity: file
  hitl:
    port: 8501
  dependencies: [generate_content]
  context_scope:
    observe: [generate_content.*]
    passthrough:
      - source.id                # Forward source ID for downstream tracking
      - generate_content.metadata

- name: format_final
  dependencies: [human_review]
  context_scope:
    observe: [human_review.*]
    passthrough:
      - source.id
```

Lineage is preserved through HITL actions — downstream actions can access namespaces from earlier ancestors through the HITL node.

## Auto-Review + HITL (Triage Pattern)

The most common production pattern: LLM pre-screens all records, routes confident decisions automatically, and sends only uncertain cases to the human.

```yaml
# Step 1: LLM auto-reviews everything
- name: auto_review
  dependencies: [generate_content]
  schema:
    decision: string             # "approve", "reject", "review"
    confidence: number
    reasoning: string
  prompt: $workflow.Auto_Review
  context_scope:
    observe: [generate_content.*]

# Step 2: Only uncertain cases go to human
- name: human_review
  kind: hitl
  granularity: file
  hitl:
    port: 8501
    timeout: 3600
  dependencies: [auto_review]
  guard:
    condition: 'auto_review.decision == "review"'
    on_false: "skip"
  context_scope:
    observe: [auto_review.*]
    passthrough:
      - generate_content.*       # Human sees full context

# Step 3: Merge human + auto decisions
- name: apply_decisions
  dependencies: [human_review]
  kind: tool
  impl: merge_review_decisions
  context_scope:
    observe: [human_review.*]
    passthrough:
      - generate_content.*
      - auto_review.decision
      - auto_review.confidence
```

The merge tool receives both auto-approved records (passed through by the guard skip) and human-reviewed records. The UDF should handle both cases:

```python
@udf_tool()
def merge_review_decisions(data: dict[str, Any]) -> list[dict[str, Any]]:
    # Fields are namespaced — each action's fields under its name
    # Both use .get() since a record may arrive from only one path
    auto_decision = data.get("auto_review", {}).get("decision", "reject")
    human_decision = data.get("human_review", {}).get("decision")

    # Human review overrides auto review when present
    decision = human_decision or auto_decision
    return [{"final_decision": decision, "reviewed_by": "human" if human_decision else "auto"}]
```

## Common Mistakes

### Not using passthrough for downstream context

HITL actions only output what the human produces. If downstream actions need upstream fields that the human didn't edit, those fields must be in `passthrough` on the HITL action.

### Guard on HITL action filtering all records

If the guard filters all records, the HITL UI has nothing to show. The action completes immediately with no human review. Use `on_false: "skip"` instead of `"filter"` to let non-matching records flow through.
