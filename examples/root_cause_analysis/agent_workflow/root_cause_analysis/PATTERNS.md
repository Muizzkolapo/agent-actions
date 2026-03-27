# Root Cause Analysis Workflow - Pattern Deep Dive

This document provides detailed technical analysis of the patterns used in the Root Cause Analysis workflow.

---

## Pattern 1: Multi-Strategy Parallel Hypothesis Generation

### Overview
Generate causal hypotheses using three independent reasoning strategies simultaneously, then aggregate results using evidence-based scoring.

### Implementation

```yaml
- name: generate_hypotheses
  dependencies: [extract_anomaly_signals]
  intent: "Generate causal hypotheses using different reasoning strategies"
  versions:
    param: reasoning_strategy
    range: ["data_driven", "topology_driven", "pattern_matching"]
    mode: parallel
  schema:
    hypotheses: array
    reasoning_path: string
    supporting_evidence: array
```

### Why Three Strategies?

**1. Data-Driven Strategy**
- Analyzes metric correlations and temporal patterns
- Identifies statistical anomalies
- Strength: Objective, quantitative
- Weakness: Can mistake correlation for causation

**2. Topology-Driven Strategy**
- Uses system architecture and dependencies
- Traces failure propagation through service graph
- Strength: Understands cascade effects
- Weakness: Misses issues not in topology

**3. Pattern-Matching Strategy**
- Matches against historical incidents
- Applies known causal patterns
- Strength: Learns from past
- Weakness: Blind to novel failure modes

### Aggregation: Composite Scoring

The `rank_causal_hypotheses` tool combines multiple signals:

```python
composite_score = (
    base_confidence * 0.35 +      # Strategy's own confidence
    evidence_score * 0.30 +        # Amount and quality of evidence
    consensus_score * 0.20 +       # Cross-strategy agreement
    pattern_bonus +                # Matches known causal pattern (0.2)
    chain_bonus                    # Part of known causal chain (0.15)
)
```

**Key Insights**:
- No single strategy dominates (weights balanced)
- Evidence and consensus matter more than confidence
- Known patterns get bonus (domain knowledge matters)
- Composite score normalized to [0, 1]

### Benefits

**Robustness**: Single strategy failure doesn't break analysis
**Diversity**: Different perspectives catch different issues
**Validation**: Cross-strategy consensus increases confidence
**Explainability**: Can show reasoning from multiple angles

---

## Pattern 2: Causal Discovery with Seed Data Enrichment

### Overview
Leverage organizational knowledge (system topology, historical incidents, causal patterns) to guide and validate causal reasoning.

### Seed Data Types

#### 1. System Topology (`system_topology.json`)
Defines architectural knowledge:

```json
{
  "services": {
    "auth-service": {
      "dependencies": ["user-db", "redis-cache"],
      "failure_modes": ["db_connection_timeout", "cache_miss_storm"]
    }
  },
  "causal_relationships": {
    "cache_miss_storm": {
      "can_cause": ["db_load_spike", "response_time_increase"],
      "typical_propagation_time": "30-60 seconds"
    }
  }
}
```

**Usage in Workflow**:
- **Topology-driven hypotheses**: Trace dependencies to find root cause
- **Impact assessment**: Identify blast radius
- **Causal chain construction**: Validate propagation paths

#### 2. Historical Incidents (`historical_incidents.json`)
Past incidents with resolutions:

```json
{
  "incidents": [
    {
      "id": "INC-2024-001",
      "root_cause": "Redis cache memory exhaustion",
      "causal_chain": [
        "Redis memory 100%",
        "Cache hit rate dropped",
        "Database overwhelmed"
      ],
      "resolution": {
        "immediate_action": "Increased Redis memory",
        "time_to_resolve": "12 minutes"
      }
    }
  ]
}
```

**Usage in Workflow**:
- **Pattern matching**: Find similar past incidents
- **Remediation planning**: Reuse proven fixes
- **Time estimation**: Predict recovery time from history
- **Validation**: Check if hypothesis matches known pattern

#### 3. Causal Patterns (`causal_patterns.json`)
Known causal relationships and validation rules:

```json
{
  "causal_rules": {
    "memory_exhaustion_rule": {
      "condition": "memory_usage > 95% AND eviction_rate > 1000/sec",
      "implies": "cache_miss_storm_likely",
      "confidence": 0.9
    }
  },
  "causal_chains": {
    "cache_failure_cascade": {
      "chain": ["cache_unavailable", "cache_miss_100%", "db_spike", ...],
      "probability": 0.85,
      "breakpoints": ["implement_fallback", "increase_db_pool"]
    }
  }
}
```

**Usage in Workflow**:
- **Hypothesis validation**: Check if matches known rules
- **Scoring bonus**: Hypotheses matching patterns get +0.2 boost
- **Mechanism validation**: Verify plausible causal mechanism exists

### Enrichment Pattern

**Standard Pattern**:
```yaml
context_scope:
  observe:
    - hypothesis_data
    - seed.system_topology
    - seed.historical_incidents
    - seed.causal_patterns
```

**Tool Access**:
```python
def generate_remediation_plan(data: dict) -> dict:
    content = data.get('content', data)

    # Access seed data
    historical_data = content.get('historical_incidents', {})
    incidents = historical_data.get('incidents', [])

    # Find similar incidents
    similar = find_similar_incidents(root_cause, incidents)

    # Extract proven remediation
    for incident in similar:
        proven_fix = incident['resolution']['immediate_action']
        # Use proven fix
```

### Why This Matters

**Without Seed Data**: Generic recommendations, no organizational context
**With Seed Data**:
- Specific runbook references
- Team-specific procedures
- Known working solutions
- Realistic time estimates

---

## Pattern 3: Weighted Evidence Scoring

### Overview
Not all evidence is equal. Score hypotheses based on evidence quantity, quality, and type.

### Evidence Types & Weights

```python
def _calculate_evidence_score(evidence: List[str]) -> float:
    # Base score: more evidence = higher score (diminishing returns)
    base_score = min(len(evidence) * 0.15, 0.6)

    # Bonus for strong evidence types
    strong_evidence_keywords = [
        'correlation',  # Statistical relationship
        'timestamp',    # Temporal precedence
        'metric',       # Quantitative measurement
        'log',          # Direct observation
        'historical',   # Past pattern
        'pattern',      # Known pattern
        'topology'      # Architectural evidence
    ]

    evidence_text = ' '.join(evidence).lower()
    bonus = sum(0.08 for keyword in strong_evidence_keywords
                if keyword in evidence_text)

    return min(base_score + bonus, 1.0)
```

### Evidence Quality Hierarchy

**Tier 1 (Strongest)**:
1. **Temporal precedence**: Cause precedes effect
2. **Mechanism**: Plausible causal pathway exists
3. **Counterfactual**: Removing cause eliminates effect

**Tier 2 (Strong)**:
4. **Correlation**: Metrics move together (r > 0.7)
5. **Historical match**: Similar to past incident
6. **Topology match**: Follows dependency graph

**Tier 3 (Supporting)**:
7. **Log messages**: Error messages support hypothesis
8. **Alert patterns**: Alert sequence matches hypothesis

### Validation Tests

Causal patterns include validation tests:

```json
{
  "validation_tests": {
    "correlation_test": {
      "method": "Calculate correlation coefficient",
      "threshold": "r > 0.7 suggests strong correlation"
    },
    "temporal_precedence_test": {
      "method": "Check cause_time < effect_time",
      "threshold": "Cause should precede effect"
    },
    "mechanism_test": {
      "method": "Verify causal chain exists in topology",
      "threshold": "All steps documented"
    }
  }
}
```

### Benefits

**Objectivity**: Reduces bias toward confident-but-unsupported hypotheses
**Transparency**: Can explain why hypothesis scored high/low
**Adaptability**: Can add new evidence types without rewriting logic

---

## Pattern 4: Consensus Detection

### Overview
When multiple independent strategies identify similar causes, confidence increases.

### Implementation

```python
def _calculate_consensus_score(hypothesis_text: str, all_hypotheses: List[Dict]) -> float:
    """Check if multiple strategies identified similar causes."""
    similar_count = sum(
        1 for h in all_hypotheses
        if any(keyword in h.get('cause', '').lower()
               for keyword in hypothesis_text.lower().split()[:3])
    )
    return min(similar_count * 0.25, 1.0)
```

### Consensus Levels

- **No consensus** (1 strategy): score = 0.25
- **Partial consensus** (2 strategies): score = 0.50
- **Full consensus** (3 strategies): score = 0.75+

### Why It Matters

**Single strategy**: Could be biased or wrong
**Two strategies agree**: Likely on the right track
**Three strategies agree**: High confidence in hypothesis

### Example

**Scenario**: Auth service errors

**Strategy 1 (Data-Driven)**:
- Hypothesis: "Database connection pool exhaustion"
- Evidence: Connection count metric spiked

**Strategy 2 (Topology-Driven)**:
- Hypothesis: "User-DB connection timeout causing auth failures"
- Evidence: Auth-service depends on user-DB

**Strategy 3 (Pattern-Matching)**:
- Hypothesis: "Connection pool exhausted (similar to INC-2024-018)"
- Evidence: Historical incident match

**Result**: All mention "connection" and "database" → consensus_score = 0.75

---

## Pattern 5: Causal Chain Construction

### Overview
Move beyond identifying root cause to building complete causal chain: Root → Intermediate → Observed Effect

### Chain Structure

```
Root Cause
    ↓ (mechanism)
Intermediate Cause 1
    ↓ (mechanism)
Intermediate Cause 2
    ↓ (mechanism)
Observed Symptom
```

### Example: Cache Failure Cascade

```
Redis memory reached 100%
    ↓ (eviction mechanism)
Cache entries evicted immediately
    ↓ (cache miss)
Cache hit rate dropped to 20%
    ↓ (fallback to DB)
Auth service overwhelmed database
    ↓ (connection exhaustion)
Database connection pool exhausted
    ↓ (timeout)
Auth service errors
```

### Validation

Each step must have:
1. **Plausible mechanism**: How does cause lead to effect?
2. **Time ordering**: Does timing make sense?
3. **Topology support**: Does service graph support this path?

### Benefits

**Understanding**: Explains not just what, but how and why
**Breakpoints**: Identifies where to intervene
**Prevention**: Shows where to add circuit breakers, fallbacks

---

## Pattern 6: Historical Learning for Remediation

### Overview
Generate remediation plans by learning from past successful resolutions.

### Learning Process

```python
def _find_similar_incidents(root_cause: str, historical_incidents: List[Dict]) -> List[Dict]:
    """Find incidents with similar root causes."""
    similar = []
    cause_keywords = set(root_cause.lower().split())

    for incident in historical_incidents:
        incident_cause = incident.get('root_cause', '').lower()
        incident_keywords = set(incident_cause.split())

        # Check keyword overlap
        overlap = cause_keywords.intersection(incident_keywords)
        if len(overlap) >= 2:
            similar.append(incident)

    return similar
```

### Remediation Generation

For similar incidents, extract:
1. **Immediate actions**: What to do right now
2. **Mitigation steps**: How to stop the bleeding
3. **Preventive measures**: How to avoid recurrence
4. **Time estimates**: How long did it take before?

### Example

**Current Issue**: "Payment service database connection timeout"

**Similar Incident Found**: INC-2024-018
- Root cause: "Order-service connection leak caused by unclosed DB connections"
- Resolution: "Rolled back deployment, restarted order-db"
- Time to resolve: "15 minutes"

**Generated Remediation**:
```json
{
  "immediate_actions": [
    {
      "action": "Rollback payment-service deployment",
      "source": "Similar to INC-2024-018",
      "effectiveness": "proven"
    }
  ],
  "recovery_time_estimate": "15 minutes (based on INC-2024-018)"
}
```

### Benefits

**Proven solutions**: Use what worked before
**Time estimates**: Realistic expectations from history
**Context preservation**: Includes source incident ID for reference
**Confidence levels**: "proven" vs "recommended" based on history match

---

## Pattern 7: Confounding Factor Detection

### Overview
Distinguish true causes from confounding factors that correlate but don't cause.

### Common Confounders

```json
{
  "confounding_factors": {
    "traffic_spike": {
      "description": "Traffic increase can mask underlying issues",
      "distinguishing_signals": [
        "Check if error rate proportional to traffic",
        "Compare to historical capacity limits"
      ]
    },
    "deployment_timing": {
      "description": "Deployment may coincide with but not cause issue",
      "distinguishing_signals": [
        "Check if rollback resolves issue",
        "Compare error patterns before/after"
      ]
    }
  }
}
```

### Detection Method

For each hypothesis, check:
1. **Correlation vs Causation**: Do metrics just correlate, or is there mechanism?
2. **Temporal precedence**: Did suspected cause actually precede effect?
3. **Confounding factor match**: Does it match known confounding pattern?

### Example

**Observed**: API errors spike at 2 PM
**Hypothesis 1**: "Deployment at 2 PM caused errors"
**Hypothesis 2**: "Scheduled batch job at 2 PM exhausted resources"

**Distinguishing**:
- Check deployment: If rollback doesn't fix → not deployment
- Check batch job schedule: If job runs at 2 PM daily → likely culprit
- Check resource metrics: If CPU spike at 2 PM regardless of deployment → batch job

---

## When to Use These Patterns

### Use Multi-Strategy Hypothesis Generation When:
- Root cause is not obvious
- Multiple failure modes possible
- Need robustness against single-strategy errors

### Use Seed Data Enrichment When:
- Organization has documented systems/processes
- Past incidents recorded
- Known failure patterns exist

### Use Weighted Evidence Scoring When:
- Hypotheses have varying evidence quality
- Need to rank/prioritize hypotheses
- Want explainable scoring

### Use Causal Chain Construction When:
- Need to understand failure mechanism
- Want to identify intervention points
- Explaining incident to stakeholders

### Use Historical Learning When:
- Past incidents are documented
- Want to reuse proven solutions
- Need realistic time estimates

---

## Anti-Patterns to Avoid

### ❌ Single Hypothesis Focus
Don't bet everything on first hypothesis. Generate multiple, rank, validate.

### ❌ Ignoring Temporal Order
Cause must precede effect. Check timestamps.

### ❌ Confusing Correlation with Causation
Just because metrics correlate doesn't mean one causes the other.

### ❌ Ignoring Known Patterns
Don't reinvent the wheel. Check if similar incident occurred before.

### ❌ Weak Evidence
"Maybe X caused Y" is not strong evidence. Demand mechanism and data.

### ❌ Over-Reliance on Single Evidence Type
Don't base conclusion solely on correlation or logs. Cross-validate.

---

## Performance Considerations

### Parallel Execution
Three hypothesis generators run in parallel:
- Sequential: ~45 seconds (3 × 15s)
- Parallel: ~15 seconds (max of 3 parallel)
- **Speedup: 3x**

### Seed Data Loading
Loaded once per workflow run, cached for all actions:
- Without caching: ~500ms per action × 8 actions = 4 seconds
- With caching: ~500ms total
- **Speedup: 8x**

### Evidence Scoring
Composite scoring is O(n) where n = number of hypotheses:
- 10 hypotheses: ~10ms
- 100 hypotheses: ~100ms
- Negligible overhead

---

## Testing Recommendations

### Unit Test Individual Components

```python
# Test evidence scoring
def test_evidence_score():
    evidence = [
        "correlation coefficient r = 0.85",
        "timestamp shows cause preceded effect",
        "matches historical pattern INC-2024-001"
    ]
    score = _calculate_evidence_score(evidence)
    assert score > 0.5  # Should be high quality

# Test consensus detection
def test_consensus():
    hypotheses = [
        {"cause": "database connection timeout"},
        {"cause": "db connection pool exhausted"},
        {"cause": "network latency spike"}
    ]
    score = _calculate_consensus_score("database connection", hypotheses)
    assert score >= 0.5  # Two mention database
```

### Integration Test Full Workflow

```bash
# Test with known root cause
agent-actions run workflows/root_cause_analysis.yml \
  --source monitoring_data:test_data/cache_exhaustion.json

# Verify output
jq '.root_cause' output.json
# Expected: Contains "cache" or "memory exhaustion"

jq '.similar_incident_count' output.json
# Expected: >= 1 (should match INC-2024-001)
```

---

## Conclusion

The Root Cause Analysis workflow demonstrates sophisticated causal reasoning through:
1. Multi-strategy diversity
2. Evidence-based validation
3. Historical learning
4. Organizational knowledge integration

These patterns are reusable across domains requiring causal analysis: system reliability, data quality issues, business metric anomalies, etc.
