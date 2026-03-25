# Root Cause Analysis

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that automates causal discovery for system anomalies — extracting signals from monitoring data, generating and validating hypotheses in parallel, constructing a causal chain, and producing a remediation plan.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API key
cp .env.example .env

# Run the workflow
agac run -a root_cause_analysis
```

Input anomaly data is read from `agent_io/staging/anomaly_data.json` (monitoring metrics, alerts, and logs). The final RCA report is written to `agent_io/target/format_analysis_output/`.

## What It Does

- Extracts and structures anomaly signals from raw monitoring data, alerts, and logs into a normalized representation for downstream reasoning.
- Generates causal hypotheses in parallel using three independent reasoning strategies, each drawing on seed data covering system topology, historical incidents, and known causal patterns.
- Aggregates the three hypothesis sets with a deterministic tool that ranks candidates by evidence strength and consensus before passing the top hypotheses forward.
- Validates the top-ranked hypotheses against available evidence and log data, then constructs an explicit causal chain tracing the path from root cause through intermediate mechanisms to observed symptoms.
- Quantifies the impact of the identified root cause on system behavior, then generates a remediation plan (using historical fixes and topology context) and formats the complete RCA report.
