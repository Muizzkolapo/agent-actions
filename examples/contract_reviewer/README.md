# Contract Reviewer

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that splits legal contracts into individual clauses, analyzes each clause for risk in parallel, aggregates findings into a unified risk report, and produces an executive summary.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API keys
cp .env.example .env

# Run the workflow
agac run -a contract_reviewer
```

Input data lives in `agent_workflow/contract_reviewer/agent_io/staging/contracts.json` (sample contracts including cloud services, software licensing, and security agreements). Risk criteria used for clause analysis are in `agent_workflow/contract_reviewer/seed_data/`. Output is written to `agent_workflow/contract_reviewer/agent_io/target/`.

## What It Does

- Splits each contract's full text into individually numbered clauses (map step) using a deterministic tool action.
- Analyzes every clause independently against the risk criteria seed data using Anthropic Claude for legal reasoning, producing a risk level, obligations, and deadlines per clause.
- Performs deep analysis on high-risk clauses only, cross-referencing the full contract text for broader context on how the clause interacts with other provisions.
- Aggregates all per-clause analyses into a single contract-level risk report at file granularity (reduce step), combining both standard and high-risk findings.
- Generates a human-readable executive summary from the aggregated report, focused at a high level without re-exposing individual clause details.
