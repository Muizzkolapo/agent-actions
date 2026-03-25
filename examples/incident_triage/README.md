# Incident Triage

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that automatically triages production incidents by classifying severity with parallel consensus voting, assessing customer and system impact, dynamically assigning a response team, and generating an actionable response plan.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API keys
cp .env.example .env

# Run the workflow
agac run -a incident_triage
```

Input data lives in `agent_workflow/incident_triage/agent_io/staging/incidents.json` (sample incident reports with monitoring data such as error rates, latency, and pod restart counts). Seed data — a team roster, service catalog, and runbook catalog — is in `agent_workflow/incident_triage/seed_data/`. Output is written to `agent_workflow/incident_triage/agent_io/target/`.

## What It Does

- Extracts structured details from the raw incident report and monitoring data, including affected services, symptoms, and timestamps.
- Runs three independent parallel severity classifiers, then aggregates their votes into a single consensus severity level (SEV1–SEV4) using a deterministic tool action.
- Assesses customer impact (revenue, user-facing effects) and system impact (blast radius, affected services) in parallel, each informed by the consensus severity.
- Dynamically assigns a response team by matching affected services against the team roster and service catalog seed data.
- Generates an initial response plan with concrete action items, then produces an executive summary only for SEV1 and SEV2 incidents before formatting the complete triage output.
