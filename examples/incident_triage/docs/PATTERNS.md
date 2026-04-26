# Agent-Actions Patterns Showcased

This document explains the agent-actions patterns demonstrated in the incident management workflows.

## Overview

These workflows showcase **production-ready patterns** inspired by [Incident.io](https://incident.io/blog/understanding-incident-triage), [Atlassian](https://www.atlassian.com/incident-management/itsm), and other modern incident management platforms.

## Pattern Catalog

### 1. Parallel Evaluation with Aggregation

**Use Case**: When single AI classifier decisions need higher accuracy/confidence

**Implementation**:
```yaml
# Step 1: Run multiple classifiers in parallel
- name: classify_severity
  versions:
    param: classifier_id
    range: [1, 2, 3]
    mode: parallel
  schema:
    severity: string
    confidence: number

# Step 2: Aggregate results
- name: aggregate_severity
  kind: tool
  impl: aggregate_severity_votes
  version_consumption:
    source: classify_severity
    pattern: merge
```

**UDF Pattern**:
```python
@udf_tool()
def aggregate_severity_votes(data: Dict[str, Any]) -> Dict[str, Any]:
    # Collect from all versions
    votes = []
    for i in range(1, 4):
        classifier_data = data.get(f'classify_severity_{i}', {})
        votes.append({
            'severity': classifier_data.get('severity'),
            'confidence': classifier_data.get('confidence')
        })

    # Weighted voting logic
    final_severity = weighted_vote(votes)

    return {
        'final_severity': final_severity,
        'confidence_score': calculate_confidence(votes),
        'is_split_decision': is_split(votes)
    }
```

**Benefits**:
- ✅ Higher accuracy through consensus
- ✅ Confidence scoring from agreement
- ✅ Detect split decisions for human review
- ✅ Reduces bias from single classifier

**When to Use**:
- Critical decisions (security, severity classification, approvals)
- Need confidence scores
- Risk mitigation required

---

### 2. Dynamic Content Injection with Passthrough

**Use Case**: Inject computed/randomized values while preserving upstream context

**Implementation**:
```yaml
- name: assign_response_team
  kind: tool
  impl: assign_team_based_on_impact
  context_scope:
    observe:
      - aggregate_severity.final_severity
      - assess_system_impact.affected_services
    passthrough:
      - aggregate_severity.*         # Forward ALL severity fields
      - assess_customer_impact.*     # Forward ALL impact fields
```

**UDF Pattern**:
```python
@udf_tool()
def assign_team_based_on_impact(data: Dict) -> Dict:
    """
    With passthrough: Return dict (not list) with ONLY new fields
    """
    # Extract what you need
    severity = data.get('final_severity')
    affected = data.get('affected_services')

    # Compute dynamic values
    teams = route_to_teams(severity, affected)
    urgency = calculate_urgency(severity)

    # Return ONLY new fields (passthrough forwards the rest)
    return {
        "assigned_teams": teams,
        "urgency_level": urgency,
        "response_message": generate_message(severity)
    }
```

**Key Points**:
- Return `dict` not `list` when using passthrough
- Return ONLY computed fields
- Framework merges with passthrough fields automatically

**Benefits**:
- ✅ Maintains full upstream context
- ✅ Clean separation of concerns
- ✅ Python control for complex logic
- ✅ Works with randomization per-record

**When to Use**:
- Routing/assignment logic
- Randomized content generation
- Complex computed values
- Conditional field injection

**Anti-Pattern** (don't do this):
```markdown
# ❌ WRONG: dispatch_task in prompts
{prompt MyPrompt}
Use this team: dispatch_task('get_team')
{end_prompt}
```
**Why it fails**: LLM may output literal text `"dispatch_task('get_team')"`

---

### 3. Conditional Execution with Guards

**Use Case**: Skip expensive operations based on conditions

**Implementation**:
```yaml
- name: generate_executive_summary
  dependencies: [generate_response_plan]
  guard:
    condition: 'final_severity == "SEV1" or final_severity == "SEV2"'
    on_false: "filter"
  schema:
    executive_summary: string
```

**How It Works**:
- Guard checks INPUT context (from dependencies)
- If condition false: record filtered out (on_false: "filter")
- Or skip action entirely (on_false: "skip")

**Benefits**:
- ✅ Reduce LLM costs (skip unnecessary calls)
- ✅ Enforce business rules
- ✅ Clear conditional logic in YAML
- ✅ No code changes needed

**When to Use**:
- Expensive operations (LLM calls, API calls)
- Business rule enforcement
- Optional steps based on data
- Escalation thresholds

---

### 4. Multi-Stage Dependency Chain

**Use Case**: Complex workflows with clear stages

**Implementation**:
```yaml
# Stage 1: Extract
- name: extract_details
  dependencies: []

# Stage 2: Parallel analysis
- name: assess_customer_impact
  dependencies: [extract_details]

- name: assess_system_impact
  dependencies: [extract_details]

# Stage 3: Synthesis (waits for both)
- name: generate_plan
  dependencies: [assess_customer_impact, assess_system_impact]
```

**Dependency DAG**:
```
extract_details
    ├──> assess_customer_impact ──┐
    └──> assess_system_impact ────┤
                                   ├──> generate_plan
```

**Benefits**:
- ✅ Parallel execution where possible
- ✅ Clear data flow
- ✅ Maintainable structure
- ✅ Framework handles scheduling

---

### 5. Version Consumption Patterns

**Pattern A: Merge (Collect All Versions)**

```yaml
- name: aggregate
  version_consumption:
    source: classify_severity
    pattern: merge
```

Result: Access all versions via `classify_severity_1`, `classify_severity_2`, etc.

**Pattern B: First (Use First Version)**
```yaml
version_consumption:
  source: generate_alternatives
  pattern: first
```

---

### 6. Structured Output Formatting

**Use Case**: Transform workflow outputs into standardized formats

**Implementation**:
```python
@udf_tool()
def format_incident_triage(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Format complete triage output"""
    # Build structured output
    result = {
        "triage_id": data.get('source_guid'),
        "incident": {
            "title": data.get('title'),
            "severity": data.get('final_severity')
        },
        "teams": {
            "assigned_teams": data.get('assigned_teams'),
            "urgency_level": data.get('urgency_level')
        }
    }

    # Return as list (standard pattern)
    return [result]
```

**Benefits**:
- ✅ Clean output structure
- ✅ API-ready formats
- ✅ Downstream integration
- ✅ Documentation generation

---

## Pattern Selection Guide

| Need | Pattern | Implementation |
|------|---------|----------------|
| Higher accuracy | Parallel Evaluation | Version + Aggregation UDF |
| Dynamic routing | Content Injection | Tool action with passthrough |
| Cost optimization | Guards | Conditional filtering |
| Complex logic | Tool actions | Python UDF |
| Parallel work | Dependencies | Multiple actions, same deps |
| Sequential stages | Dependencies | Chain with dependencies |

## Anti-Patterns to Avoid

### ❌ 1. dispatch_task() in Prompts
**Problem**: Unreliable, LLM may output literal text

**Solution**: Use tool action injection instead

### ❌ 2. Guard on Wrong Action
**Problem**: Guard checks INPUT, not OUTPUT

```yaml
# WRONG
- name: validate_data
  guard:
    condition: 'status == "valid"'  # Checks INPUT!

# CORRECT
- name: validate_data
  # No guard - this produces status

- name: use_validated
  dependencies: [validate_data]
  guard:
    condition: 'status == "valid"'  # Checks validate_data OUTPUT
```

### ❌ 3. Missing Passthrough
**Problem**: Lose upstream context after tool action

```yaml
# WRONG
- name: inject_data
  context_scope:
    observe:
      - upstream.field    # Only observes, doesn't forward

# CORRECT
- name: inject_data
  context_scope:
    observe:
      - upstream.field
    passthrough:
      - upstream.*        # Forward everything
```

### ❌ 4. UDF Returns Dict Instead of List
**Problem**: Framework expects list for record operations

```python
# WRONG (unless using passthrough)
return {'result': 'value'}

# CORRECT
return [{'result': 'value'}]

# CORRECT with passthrough
return {'result': 'value'}  # Only new fields
```

## Testing Patterns

### Pattern Testing
```bash
# Test single UDF
python -c "from tools.aggregate_severity_votes import *; print(aggregate_severity_votes({...}))"

# Test full workflow
agac run -a incident_triage --input test_data.json
```

### Output Validation
```python
# Verify output structure
import json

with open('target/format_triage_output/result.json') as f:
    result = json.load(f)
    assert 'incident' in result[0]
    assert 'teams' in result[0]
```

## Resources

- [Agent Actions Docs](https://github.com/yourusername/agent-actions)
- [Workflow Patterns Reference](../../.claude/skills/agac-agent-skills/references/workflow-patterns.md)
- [UDF Patterns Reference](../../.claude/skills/agac-agent-skills/references/udf-patterns.md)
- [Dynamic Content Injection](../../.claude/skills/agac-agent-skills/references/dynamic-content-injection.md)

## Contributing

Found a new pattern? Contribute it back:

1. Document the pattern clearly
2. Provide working example code
3. Explain use cases and benefits
4. Submit PR with tests
