# Root Cause Analysis Workflow

Automated root cause analysis using causal discovery and multi-strategy reasoning to identify the true causes of system anomalies.

## Overview

This workflow demonstrates a CausalLens-inspired approach to RCA that uses parallel hypothesis generation with different reasoning strategies, evidence-based validation, causal chain construction, and remediation planning enriched with historical data.

## Workflow Diagram

```
                    ┌─────────────────────────┐
                    │ extract_anomaly_signals │
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
    ┌─────────┴───────┐ ┌───────┴───────┐ ┌──────┴──────┐
    │generate_hypotheses│generate_hypotheses│generate_hypotheses│
    │   data_driven   │ │topology_driven│ │pattern_matching│
    │     (LLM)       │ │    (LLM)      │ │    (LLM)    │
    └─────────┬───────┘ └───────┬───────┘ └──────┬──────┘
              │                 │                 │
              └─────────────────┼─────────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │    rank_hypotheses      │
                    │        (Tool)           │
                    │  [version_consumption]  │
                    │  [weighted scoring]     │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │   validate_hypotheses   │
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │  construct_causal_chain │
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │    quantify_impact      │
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │  generate_remediation   │
                    │        (Tool)           │
                    │ [seed data enrichment]  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │  format_analysis_output │
                    │        (Tool)           │
                    └─────────────────────────┘
```

## Key Patterns Demonstrated

### 1. Multi-Strategy Hypothesis Generation
Parallel reasoning with different approaches:
```yaml
versions:
  range: ["data_driven", "topology_driven", "pattern_matching"]
  mode: parallel
```

**Strategies:**
- **data_driven**: Statistical correlations, metric patterns, temporal relationships
- **topology_driven**: System architecture, dependency tracing, network analysis
- **pattern_matching**: Historical incidents, known failure patterns

### 2. Weighted Hypothesis Ranking
Tool aggregates and scores hypotheses:
```yaml
version_consumption:
  source: generate_hypotheses
  pattern: merge
```

Scoring factors:
- Base confidence from strategy
- Evidence strength
- Cross-strategy consensus
- Pattern matching bonus
- Known causal chain bonus

### 3. Seed Data Enrichment
Remediation uses historical data for intelligent recommendations:
```yaml
context_scope:
  seed_data:
    system_topology: $file:system_topology.json
    historical_incidents: $file:historical_incidents.json
    causal_patterns: $file:causal_patterns.json
```

### 4. Causal Chain Construction
Build complete path from root cause to symptoms:
```
Root Cause → Intermediate Causes → Observed Symptoms
     │              │                    │
     └──────────────┴────────────────────┘
              Propagation Path
```

## Data Flow

```
agent_io/
├── staging/          # Place anomaly data here
│   └── anomaly_data.json
├── source/           # Auto-generated with metadata
└── target/           # Output from each action
    ├── extract_anomaly_signals/
    ├── generate_hypotheses_data_driven/
    ├── generate_hypotheses_topology_driven/
    ├── generate_hypotheses_pattern_matching/
    ├── rank_hypotheses/
    ├── validate_hypotheses/
    ├── construct_causal_chain/
    ├── quantify_impact/
    ├── generate_remediation/
    └── format_analysis_output/
```

## Input Format

Place anomaly data in `agent_io/staging/`:

```json
[
  {
    "monitoring_data": {
      "timestamp_range": "2024-01-15T14:00:00Z to 2024-01-15T14:45:00Z",
      "metrics": [
        {"time": "14:00", "service": "api-gateway", "cpu_percent": 45, "error_rate": 0.1, "latency_p99_ms": 150},
        {"time": "14:25", "service": "api-gateway", "cpu_percent": 95, "error_rate": 35.8, "latency_p99_ms": 8500}
      ]
    },
    "alerts": [
      {"time": "14:22:18Z", "severity": "CRITICAL", "alert": "HighCPUUsage", "service": "api-gateway"}
    ],
    "logs": [
      {"timestamp": "2024-01-15T14:22:34Z", "level": "ERROR", "service": "database-primary", "message": "Connection pool exhausted"}
    ]
  }
]
```

## Output

The final `format_analysis_output` produces:

```json
{
  "report_type": "Root Cause Analysis",
  "executive_summary": "HIGH incident affecting 3 components. Root cause: Database connection pool exhaustion...",

  "anomaly_detection": {
    "anomaly_type": "resource_exhaustion",
    "affected_components": ["api-gateway", "user-service", "database-primary"],
    "severity": "HIGH"
  },

  "causal_analysis": {
    "root_cause": "Batch import job consuming all database connections",
    "intermediate_causes": ["Connection pool exhaustion", "Query timeouts", "Circuit breaker open"],
    "propagation_path": ["batch-processor", "database-primary", "api-gateway", "user-service"]
  },

  "impact_assessment": {
    "impact_magnitude": "HIGH",
    "blast_radius": ["api-gateway", "user-service", "checkout-service"],
    "business_impact": "35% of checkout requests failing"
  },

  "remediation_plan": {
    "immediate_actions": [{"action": "Kill batch job", "effectiveness": "proven"}],
    "preventive_measures": [{"measure": "Rate limit batch imports"}],
    "recovery_time_estimate": "15 minutes (based on historical data)"
  }
}
```

## Seed Data

Reference data in `seed_data/`:

### `system_topology.json`
```json
{
  "services": {
    "api-gateway": {
      "dependencies": ["user-service", "payment-service"],
      "health_metrics": ["latency_p99", "error_rate", "cpu_usage"]
    }
  }
}
```

### `historical_incidents.json`
```json
{
  "incidents": [
    {
      "id": "INC-2024-001",
      "root_cause": "database connection exhaustion",
      "resolution": {
        "immediate_action": "Restart connection pool",
        "preventive_measure": "Implement connection limits per service"
      },
      "time_to_resolve": "20 minutes"
    }
  ]
}
```

### `causal_patterns.json`
```json
{
  "causal_rules": {
    "connection_exhaustion": {
      "symptoms": ["timeout errors", "high latency"],
      "typical_causes": ["traffic spike", "connection leak", "slow queries"]
    }
  }
}
```

## Running the Workflow

```bash
# Run the analysis
agac run -a root_cause_analysis

```

## Tools

| Tool | Purpose |
|------|---------|
| `rank_causal_hypotheses` | Multi-factor scoring and ranking |
| `generate_remediation_plan` | Historical data enrichment for recommendations |
| `format_rca_report` | Structure final analysis report |

## Customization

- **Reasoning strategies**: Add/modify strategies in versions range
- **Scoring weights**: Adjust in `rank_causal_hypotheses.py`
- **Historical matching**: Update similarity logic in `generate_remediation_plan.py`
- **Add seed data**: Expand topology, incidents, and patterns files

## Recommended Datasets

For testing with real system logs:
- [Loghub](https://github.com/logpai/loghub) - HDFS, OpenStack, Hadoop logs
- [AIT Anomaly Detection Datasets](https://github.com/ait-aecid/anomaly-detection-log-datasets) - Pre-processed samples
- Sample data included: Database exhaustion, External API outage scenarios
