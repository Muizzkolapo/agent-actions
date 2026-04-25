# Aggregation Patterns

How to merge outputs from parallel branches or versioned actions.

---

## Version Merge (Parallel Voting)

N parallel instances of the same action, merged into one record for aggregation.

```yaml
- name: score_quality
  versions: { param: scorer_id, range: [1, 2, 3], mode: parallel }

- name: aggregate_scores
  dependencies: [score_quality]
  kind: tool
  impl: aggregate_quality_scores
  version_consumption: { source: score_quality, pattern: merge }
  context_scope:
    observe:
      - score_quality_1.*
      - score_quality_2.*
      - score_quality_3.*
```

Or use the base name with wildcard (resolver expands automatically):
```yaml
    observe: [score_quality.*]
```

### UDF for version merge

Version merge delivers **double-nested data** — the version namespace wraps the version's full content (including upstream namespaces carried forward):

```python
@udf_tool()
def aggregate_quality_scores(data: dict[str, Any]) -> dict:
    scores = []
    for i in range(1, 4):
        key = f"score_quality_{i}"
        scorer_ns = data.get(key, {})
        # Unwrap inner namespace: data["score_quality_1"]["score_quality_1"]
        scorer = scorer_ns.get(key, scorer_ns) if isinstance(scorer_ns, dict) else {}
        helpfulness = scorer.get("helpfulness_score", 0)
        specificity = scorer.get("specificity_score", 0)
        authenticity = scorer.get("authenticity_score", 0)
        weighted = helpfulness * 0.35 + specificity * 0.30 + authenticity * 0.35
        scores.append(weighted)

    return {
        "consensus_score": round(sum(scores) / len(scores), 1),
        "score_spread": round(max(scores) - min(scores), 1),
    }
```

---

## Fan-In (Different Actions)

Two different actions with different schemas converge at one point.

```yaml
- name: merge_point
  dependencies: [branch_a_end, branch_b_end]
  context_scope:
    observe:
      - branch_a_end.*
      - branch_b_end.*
```

No special merge syntax. The bus has both namespaces.

**Key difference from version merge:** Fan-in is different actions with different schemas on the same record. Version merge is the same action with N instances producing N separate records that get combined into one.

---

## reduce_key (Field-Based Grouping)

Groups records by a field value before merging. Used when multiple validators score the same item.

```yaml
- name: aggregate
  dependencies: [validator]
  reduce_key: source.item_id
```

Records with the same `item_id` are grouped together for aggregation.

---

## FILE Mode Aggregation (N->1)

```python
@udf_tool(granularity=Granularity.FILE)
def aggregate_risk(data: list[dict]) -> FileUDFResult:
    """All clause analyses -> 1 risk summary."""
    high_risk = [item for item in data if item.get("risk_level") == "high"]
    return FileUDFResult(outputs=[
        {"source_index": 0, "data": {
            "overall_risk": "high" if high_risk else "low",
            "clause_count": len(data),
            "high_risk_count": len(high_risk),
        }}
    ])
```

---

## LLM Aggregation (No UDF)

For simple aggregation, use an LLM action instead of a tool:

```yaml
- name: generate_summary
  dependencies: [analyze_clause]
  granularity: File  # LLM sees ALL records
  context_scope:
    observe: [analyze_clause.*]
  prompt: $workflow.Summarize_Analyses
```
