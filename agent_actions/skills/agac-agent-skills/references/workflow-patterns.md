# Workflow Patterns

Common patterns for multi-action workflows.

---

## 1. Sequential Pipeline

```yaml
actions:
  - name: extract_claims
    prompt: $workflow.Extract_Claims

  - name: score_quality
    dependencies: [extract_claims]
    context_scope:
      observe: [extract_claims.*]
```

Each action adds its namespace. Next action observes previous.

---

## 2. Diamond / Fan-In

```
          +-> assess_customer_impact --+
source -->|                            |--> assign_response_team
          +-> assess_system_impact ----+
```

```yaml
- name: assess_customer_impact
  dependencies: [classify_severity]

- name: assess_system_impact
  dependencies: [classify_severity]

- name: assign_response_team
  dependencies: [assess_customer_impact, assess_system_impact]
  context_scope:
    observe:
      - assess_customer_impact.*
      - assess_system_impact.*
```

No merge operator needed. The bus has both namespaces. `dependencies` controls when, `observe` controls what.

---

## 3. Parallel Voting / Consensus

```yaml
- name: score_quality
  versions: { param: scorer_id, range: [1, 2, 3], mode: parallel }
  context_scope:
    observe: [extract_claims.*, source.review_text, seed.rubric]
    drop: [source.star_rating]  # bias prevention

- name: aggregate_scores
  dependencies: [score_quality]
  kind: tool
  impl: aggregate_quality_scores
  version_consumption: { source: score_quality, pattern: merge }
  context_scope:
    observe: [score_quality.*]  # resolver expands to _1, _2, _3
```

Aggregate tool receives double-nested data:
```python
@udf_tool()
def aggregate_quality_scores(data: dict[str, Any]) -> dict:
    scores = []
    for i in range(1, 4):
        key = f"score_quality_{i}"
        scorer_ns = data.get(key, {})
        scorer = scorer_ns.get(key, scorer_ns) if isinstance(scorer_ns, dict) else {}
        scores.append(scorer.get("overall_score", 0))
    return {"consensus_score": round(sum(scores) / len(scores), 1)}
```

---

## 4. Map-Reduce

```
source (1 doc) --> split (N records) --> process each --> aggregate (1 summary)
```

```yaml
- name: split_into_clauses
  kind: tool
  impl: split_contract
  # Record tool returning list[dict] = 1->N flatten

- name: analyze_clause
  dependencies: [split_into_clauses]
  # Runs once per clause (Record granularity)

- name: aggregate_risk
  dependencies: [analyze_clause]
  kind: tool
  impl: aggregate_risk_summary
  granularity: File  # Sees ALL clause records
```

Split tool (Record mode, 1->N):
```python
@udf_tool()
def split_contract(data: dict) -> list[dict]:
    text = data["source"]["full_text"]
    return [{"clause_text": c, "clause_num": i} for i, c in enumerate(split(text))]
```

Aggregate tool (FILE mode, N->1):
```python
@udf_tool(granularity=Granularity.FILE)
def aggregate_risk_summary(data: list[dict]) -> FileUDFResult:
    risks = [item.get("risk_level", "low") for item in data]
    return FileUDFResult(outputs=[
        {"source_index": 0, "data": {
            "overall_risk": max(risks),
            "clause_count": len(data),
        }}
    ])
```

---

## 5. Guard Decision Flow

```yaml
- name: generate_response
  dependencies: [aggregate_scores]
  guard:
    condition: 'aggregate_scores.consensus_score >= 6'
    on_false: filter   # low-quality records removed
```

`filter`: record gone. `skip`: record survives with null namespace.

---

## 6. LLM + Tool Alternation

```yaml
- name: generate_description   # LLM
- name: fetch_prices           # Tool (grounding)
  dependencies: [generate_description]
  kind: tool
  impl: fetch_competitor_prices
- name: write_marketing        # LLM (grounded by tool data)
  dependencies: [fetch_prices]
  context_scope:
    observe: [generate_description.*, fetch_prices.*]
```

Tool results ground the next LLM call. Same namespace rules for both.

---

## 7. Cross-Workflow Chaining

```yaml
# In downstream workflow config
upstream:
  workflow: upstream_workflow_name
  actions: [format_output]
```

All upstream namespaces preserved. Downstream adds its own on top.

---

## 8. Context Isolation (Bias Prevention)

```yaml
- name: score_quality
  versions: { range: [1, 2, 3] }
  context_scope:
    observe: [extract_claims.*, source.review_text]
    drop: [source.star_rating]  # scorers never see user's rating
```

DROP excludes from prompt only. Data stays on bus for downstream.

---

## 9. Non-JSON Field-by-Field

For models that can't produce JSON (e.g., Ollama 3B):

```yaml
- name: classify_issue
  json_mode: false
  output_field: issue_type

- name: assess_severity
  dependencies: [classify_issue]
  json_mode: false
  output_field: severity
  context_scope:
    observe: [classify_issue.*]
```

Each action stores: `content["action_name"]["output_field"] = "plain text"`.

---

## 10. Passthrough Routing

```yaml
context_scope:
  observe: [pick_pattern.*]
  passthrough:
    - consolidate_answer_from_source.final_source_quote
    - source.review_id
```

Passthrough fields flow to output (zero tokens). The LLM never sees them.
