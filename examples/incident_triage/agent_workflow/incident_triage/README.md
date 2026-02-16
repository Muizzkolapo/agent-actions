# Incident Triage Workflow

Automated incident triage system that classifies severity, assesses impact, assigns teams, and generates initial response plans.

## Overview

This workflow demonstrates production-ready incident management automation using LLM-powered analysis combined with deterministic tool actions for team assignment and formatting.

## Workflow Diagram

```
                    ┌─────────────────────────┐
                    │  extract_incident_details│
                    │        (LLM)            │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │    classify_severity    │
                    │   (LLM - 3x parallel)   │
                    │  [versions: 1-3]        │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴─────────────┐
                    │   aggregate_severity    │
                    │        (Tool)           │
                    │  [weighted consensus]   │
                    └───────────┬─────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
    ┌─────────┴───────┐  ┌──────┴──────┐  ┌──────┴──────┐
    │assess_customer_ │  │assess_system│  │             │
    │    impact       │  │   _impact   │  │             │
    │    (LLM)        │  │   (LLM)     │  │             │
    └─────────┬───────┘  └──────┬──────┘  │             │
              │                 │         │             │
              └────────┬────────┘         │             │
                       │                  │             │
            ┌──────────┴──────────┐       │             │
            │ assign_response_team│       │             │
            │       (Tool)        │       │             │
            │ [dynamic injection] │       │             │
            └──────────┬──────────┘       │             │
                       │                  │             │
            ┌──────────┴──────────┐       │             │
            │generate_response_plan│      │             │
            │       (LLM)         │       │             │
            └──────────┬──────────┘       │             │
                       │                  │             │
         ┌─────────────┼─────────────┐    │             │
         │             │             │    │             │
         │   ┌─────────┴─────────┐   │    │             │
         │   │generate_executive_│   │    │             │
         │   │     summary       │   │    │             │
         │   │ (LLM - guarded)   │   │    │             │
         │   │ [SEV1/SEV2 only]  │   │    │             │
         │   └─────────┬─────────┘   │    │             │
         │             │             │    │             │
         └─────────────┼─────────────┘    │             │
                       │                  │             │
            ┌──────────┴──────────┐       │             │
            │ format_triage_output│───────┘             │
            │       (Tool)        │                     │
            └─────────────────────┘                     │
```

## Key Patterns Demonstrated

### 1. Parallel Evaluation with Versions
Multiple independent classifiers evaluate severity simultaneously:
```yaml
versions:
  range: [1, 3]
  mode: parallel
```

### 2. Aggregation with Consensus
Tool action aggregates parallel results using weighted voting:
```yaml
version_consumption:
  source: classify_severity
  pattern: merge
```

### 3. Dynamic Content Injection
Team assignment uses seed data (team roster, service catalog) to inject context:
```yaml
context_scope:
  observe:
    - aggregate_severity.final_severity
    - assess_system_impact.affected_services
  passthrough:
    - aggregate_severity.*
    - assess_customer_impact.*
```

### 4. Conditional Execution with Guards
Executive summary only generated for high-severity incidents:
```yaml
guard:
  condition: 'final_severity == "SEV1" or final_severity == "SEV2"'
  on_false: "filter"
```

## Data Flow

```
agent_io/
├── staging/          # Place incident JSON files here
│   └── incidents.json
├── source/           # Auto-generated with metadata
└── target/           # Output from each action
    ├── extract_incident_details/
    ├── classify_severity_1/
    ├── classify_severity_2/
    ├── classify_severity_3/
    ├── aggregate_severity/
    ├── assess_customer_impact/
    ├── assess_system_impact/
    ├── assign_response_team/
    ├── generate_response_plan/
    ├── generate_executive_summary/
    └── format_triage_output/
```

## Input Format

Place incident data in `agent_io/staging/`:

```json
[
  {
    "incident_report": "Description of the incident...",
    "monitoring_data": {
      "error_rate": {"service_name": 45.2},
      "latency_p99_ms": {"service_name": 8500}
    },
    "timestamp": "2024-01-15T14:32:00Z"
  }
]
```

## Output

The final `format_triage_output` produces structured triage reports:

```json
{
  "triage_id": "uuid",
  "incident": { "title": "...", "description": "..." },
  "severity": { "final_severity": "SEV2", "confidence_score": 0.85 },
  "impact": { "customer_impact": {...}, "system_impact": {...} },
  "teams": { "assigned_teams": ["backend-oncall"], "urgency_level": "..." },
  "response": { "immediate_actions": [...], "investigation_steps": [...] },
  "executive_summary": { "summary": "..." }
}
```

## Seed Data

Reference data in `seed_data/`:
- `team_roster.json` - On-call teams, contacts, SLAs
- `service_catalog.json` - Service ownership, dependencies
- `runbook_catalog.json` - Standard operating procedures

## Running the Workflow

```bash
# Run the workflow
agac run -a incident_triage

```

## Tools

| Tool | Purpose |
|------|---------|
| `aggregate_severity_votes` | Weighted consensus from parallel classifiers |
| `assign_team_based_on_impact` | Dynamic team routing with seed data enrichment |
| `format_incident_triage` | Structure final output |

## Customization

- **Severity thresholds**: Modify `SEVERITY_WEIGHTS` in `aggregate_severity_votes.py`
- **Team routing rules**: Update `TEAM_ROUTING` in `assign_team_based_on_impact.py`
- **Guard conditions**: Adjust severity filter in `generate_executive_summary` action
