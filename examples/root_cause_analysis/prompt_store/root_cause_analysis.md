# Root Cause Analysis Prompts

{prompt Extract_Anomaly_Signals}
You are a system reliability engineer analyzing monitoring data to identify anomaly signals.

## INPUT DATA

**Monitoring Data**: {{ source.monitoring_data }}

**Alerts**: {{ source.alerts }}

**Logs**: {{ source.logs }}

## TASK

Extract and structure anomaly signals from the raw monitoring data:

1. **Anomaly Type**: Classify the type of anomaly (latency, error, resource, connectivity)
2. **Affected Components**: List all systems/services affected
3. **Observed Symptoms**: Observable manifestations of the problem
4. **Metric Deviations**: Quantified deviations from baseline
5. **Timestamp Range**: When the anomaly was observed
6. **Severity**: Severity level based on impact

## ANOMALY TYPES

- **latency_spike**: Response time degradation
- **error_rate_increase**: Elevated error rates
- **resource_exhaustion**: CPU/memory/disk issues
- **connectivity_issue**: Network/connection problems
- **cascade_failure**: Multiple dependent failures

## OUTPUT FORMAT

```json
{
  "anomaly_type": "type of anomaly",
  "affected_components": ["component1", "component2"],
  "observed_symptoms": ["symptom 1", "symptom 2"],
  "metric_deviations": [
    {"metric": "name", "baseline": 0, "current": 0, "deviation_pct": 0}
  ],
  "timestamp_range": "start to end",
  "severity": "CRITICAL | HIGH | MEDIUM | LOW"
}
```

{end_prompt}

{prompt Generate_Hypotheses}
You are reasoning engine {{ i }} of {{ version.length }} in a hypothesis generation ensemble.

## YOUR REASONING STRATEGY

{% if version.first %}
**Primary Strategy: DATA-DRIVEN ANALYSIS**
Focus on statistical patterns, correlations in metrics, and temporal relationships.
- Identify metrics that deviated BEFORE symptoms appeared
- Look for leading indicators and lagging effects
- Analyze time-series patterns and anomaly timing
{% elif version.last %}
**Primary Strategy: PATTERN MATCHING**
Apply known failure patterns, similar historical incidents, and common causes.
- Match against known failure modes for this anomaly type
- Consider historical incidents with similar signatures
- Apply domain knowledge about common root causes
{% else %}
**Primary Strategy: TOPOLOGY-DRIVEN ANALYSIS**
Consider system architecture, dependency relationships, and network topology.
- Trace back from affected components through dependencies
- Identify upstream services that could cause downstream failures
- Analyze the blast radius and propagation paths
{% endif %}

## ANOMALY DETAILS

**Anomaly Type**: {{ extract_anomaly_signals.anomaly_type }}

**Affected Components**: {{ extract_anomaly_signals.affected_components }}

**Observed Symptoms**: {{ extract_anomaly_signals.observed_symptoms }}

**Metric Deviations**: {{ extract_anomaly_signals.metric_deviations }}

## TASK

Using your assigned strategy, generate 3-5 causal hypotheses about what might have caused this anomaly. For each hypothesis:

1. **Cause**: The suspected root cause
2. **Mechanism**: How this cause leads to the observed symptoms
3. **Confidence**: Your confidence level (0.0-1.0)
4. **Evidence**: What evidence supports this hypothesis

## OUTPUT FORMAT

```json
{
  "hypotheses": [
    {
      "cause": "suspected root cause",
      "mechanism": "how it causes the symptoms",
      "confidence": 0.0-1.0,
      "evidence": ["evidence point 1", "evidence point 2"]
    }
  ],
  "reasoning_path": "description of your reasoning approach",
  "supporting_evidence": ["overall evidence used"]
}
```

## GUIDELINES

- Be specific about causes (not "something failed" but "database connection pool exhaustion")
- Include testable predictions for each hypothesis
- Consider both direct and indirect causes
- Rank by plausibility based on available evidence

{end_prompt}

{prompt Validate_Hypotheses}
You are a senior engineer validating causal hypotheses against available evidence.

## TOP HYPOTHESES TO VALIDATE

{{ rank_hypotheses.top_hypotheses }}

## AVAILABLE EVIDENCE

**Anomaly Details**:
- Type: {{ extract_anomaly_signals.anomaly_type }}
- Components: {{ extract_anomaly_signals.affected_components }}
- Symptoms: {{ extract_anomaly_signals.observed_symptoms }}

**Logs**: {{ source.logs }}

## TASK

Validate each top hypothesis against the available evidence:

1. **Validated Hypotheses**: Which hypotheses are supported by evidence
2. **Evidence Analysis**: How the evidence supports or refutes each hypothesis
3. **Confidence Scores**: Updated confidence based on validation
4. **Contradicting Evidence**: Evidence that contradicts any hypothesis

## VALIDATION CRITERIA

- Does the timeline of events match the hypothesis?
- Are there log entries that confirm or deny the cause?
- Does the affected component pattern match expectations?
- Are there any contradicting signals?

## OUTPUT FORMAT

```json
{
  "validated_hypotheses": [
    {
      "cause": "hypothesis cause",
      "validation_status": "CONFIRMED | LIKELY | POSSIBLE | UNLIKELY | REFUTED",
      "supporting_evidence": ["evidence"],
      "confidence_adjustment": "+0.1 | -0.2 | etc"
    }
  ],
  "evidence_analysis": "overall analysis of evidence",
  "confidence_scores": {
    "hypothesis_1": 0.0-1.0
  },
  "contradicting_evidence": ["any contradicting findings"]
}
```

{end_prompt}

{prompt Construct_Causal_Chain}
You are a causal reasoning specialist constructing the complete causal chain.

## VALIDATED HYPOTHESES

{{ validate_hypotheses.validated_hypotheses }}

**Evidence Analysis**: {{ validate_hypotheses.evidence_analysis }}

## AFFECTED COMPONENTS

{{ extract_anomaly_signals.affected_components }}

## TASK

Construct the complete causal chain from root cause to observed symptoms:

1. **Root Cause**: The ultimate/originating cause
2. **Intermediate Causes**: Chain of events between root and symptoms
3. **Causal Mechanism**: How the root cause propagates
4. **Propagation Path**: Ordered path through the system
5. **Contributing Factors**: Conditions that enabled the failure

## OUTPUT FORMAT

```json
{
  "root_cause": "the ultimate root cause",
  "intermediate_causes": [
    {"cause": "intermediate event", "sequence": 1}
  ],
  "causal_mechanism": "how the root cause leads to symptoms",
  "propagation_path": ["step1", "step2", "step3", "observed_symptom"],
  "contributing_factors": ["factor 1", "factor 2"]
}
```

## GUIDELINES

- The root cause should be actionable (something that can be fixed)
- Include timing where possible
- Consider both technical and process factors
- Distinguish between proximate and ultimate causes

{end_prompt}

{prompt Quantify_Impact}
You are an impact assessment specialist quantifying the effects of the root cause.

## CAUSAL ANALYSIS

**Root Cause**: {{ construct_causal_chain.root_cause }}

**Causal Mechanism**: {{ construct_causal_chain.causal_mechanism }}

**Propagation Path**: {{ construct_causal_chain.propagation_path }}

## OBSERVED DEVIATIONS

{{ extract_anomaly_signals.metric_deviations }}

## MONITORING DATA

{{ source.monitoring_data }}

## TASK

Quantify the impact of the root cause on system behavior:

1. **Impact Magnitude**: Overall severity (CRITICAL/HIGH/MEDIUM/LOW)
2. **Affected Metrics**: Which metrics were impacted and by how much
3. **Estimated Effect Size**: Quantified impact
4. **Blast Radius**: Systems/components affected directly and indirectly
5. **Business Impact**: Translation to business terms

## OUTPUT FORMAT

```json
{
  "impact_magnitude": "CRITICAL | HIGH | MEDIUM | LOW",
  "affected_metrics": [
    {"metric": "name", "impact": "description", "change": "quantified change"}
  ],
  "estimated_effect_size": "quantified overall impact",
  "blast_radius": ["directly affected", "indirectly affected"],
  "business_impact": "business impact description"
}
```

## IMPACT LEVELS

- **CRITICAL**: Complete service unavailability, data loss, security breach
- **HIGH**: Major functionality impaired, significant user impact
- **MEDIUM**: Partial degradation, workarounds available
- **LOW**: Minor impact, limited scope

{end_prompt}
