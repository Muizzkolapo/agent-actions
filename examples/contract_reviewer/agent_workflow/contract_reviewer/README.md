# Contract Reviewer Workflow

Automated contract risk analysis using the Map-Reduce pattern: split contracts into clauses, analyze each independently, then aggregate into a unified risk report.

## Overview

This workflow demonstrates how to process large documents by breaking them into smaller units, processing each in parallel, and aggregating the results. A contract is split into individual clauses, each clause is analyzed for risk and obligations, high-risk clauses receive deeper scrutiny, and all findings are combined into an executive summary.

## Workflow Diagram

```
         ┌──────────────────────────────┐
         │     split_into_clauses       │
         │          (Tool)              │
         │  MAP: 1 contract → N clauses │
         └──────────────┬───────────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
  ┌───────┴──────┐ ┌───┴───┐ ┌──────┴───────┐
  │analyze_clause│ │  ...  │ │analyze_clause│
  │   (LLM)     │ │  ...  │ │   (LLM)      │
  │  Anthropic   │ │       │ │  Anthropic    │
  └───────┬──────┘ └───┬───┘ └──────┬───────┘
          │             │             │
          │    ┌────────┴────────┐    │
          │    │  GUARD: high?   │    │
          │    └────────┬────────┘    │
          │             │             │
          │    ┌────────┴────────┐    │
          │    │ flag_high_risk  │    │
          │    │     (LLM)      │    │
          │    │   Anthropic    │    │
          │    └────────┬────────┘    │
          │             │             │
          └─────────────┼─────────────┘
                        │
         ┌──────────────┴───────────────┐
         │   aggregate_risk_summary     │
         │          (Tool)              │
         │  REDUCE: N clauses → 1 report│
         │    [FILE granularity]        │
         └──────────────┬───────────────┘
                        │
         ┌──────────────┴───────────────┐
         │ generate_executive_summary   │
         │          (LLM)              │
         │       OpenAI GPT-4o         │
         └──────────────────────────────┘
```

## Key Patterns Demonstrated

### 1. Map-Reduce Document Processing
Split a large document into units, process each independently, then aggregate:
```yaml
# MAP: split_into_clauses (Tool) — 1 contract in, N clauses out
# PROCESS: analyze_clause (LLM) — per-clause analysis
# REDUCE: aggregate_risk_summary (Tool, FILE granularity) — N clauses → 1 report
```

### 2. FILE Granularity Aggregation
The `aggregate_risk_summary` tool sees ALL clause records at once, enabling cross-clause analysis:
```yaml
granularity: File    # Receives list[dict] instead of single dict
```

### 3. Guard-Based Filtering
Only high-risk clauses receive deep legal analysis:
```yaml
guard:
  condition: 'risk_level == "high"'
  on_false: "filter"
```

### 4. Context Scoping
- `observe`: Fields the LLM needs to read
- `passthrough`: Metadata carried through without LLM seeing it
- `drop`: Explicitly excluded fields to keep context focused

### 5. Multi-Vendor Model Selection
- **Anthropic Claude** for clause analysis (legal reasoning)
- **OpenAI GPT-4o** for executive summary (concise business writing)

## Context Flow

```
source (contract)
  │
  ├─ full_text ──────────→ split_into_clauses ──→ analyze_clause
  ├─ contract_id ────────→ passthrough chain ───→ aggregate
  ├─ title ──────────────→ passthrough chain ───→ aggregate
  └─ parties ────────────→ passthrough chain ───→ aggregate

seed_data
  └─ risk_criteria ──────→ analyze_clause, flag_high_risk

analyze_clause.*  ───────→ aggregate_risk_summary (FILE granularity)
flag_high_risk.*  ───────→ aggregate_risk_summary (optional, guarded)

aggregate_risk_summary.* → generate_executive_summary
```

## Data Description

### Input: `contracts.json`
Array of contract objects, each with:
- `contract_id`: Unique identifier
- `title`: Contract name
- `parties`: Array of party names
- `full_text`: Complete contract text with numbered clauses

Three sample contracts are included:
1. **CTR-2024-001** (Low risk) — Standard cloud infrastructure services agreement with balanced terms
2. **CTR-2024-002** (Medium risk) — Enterprise software licensing with three parties and some unusual IP/payment terms
3. **CTR-2024-003** (High risk) — Managed security operations with aggressive liability exclusions, one-sided termination, and tight deadlines

### Seed Data: `risk_criteria.json`
Risk assessment criteria organized by level (high/medium/low) with specific indicators, obligation categories, and scoring guidance.

## File Structure

```
contract_reviewer/
├── .env.example                          # API key placeholders
├── agent_actions.yml                     # Project configuration
├── agent_workflow/contract_reviewer/
│   ├── README.md                         # This file
│   ├── agent_config/
│   │   └── contract_reviewer.yml         # Workflow definition (5 actions)
│   ├── agent_io/staging/
│   │   └── contracts.json                # 3 sample contracts
│   └── seed_data/
│       └── risk_criteria.json            # Risk assessment criteria
├── prompt_store/
│   └── contract_reviewer.md              # LLM prompts (3 actions)
├── schema/contract_reviewer/
│   ├── split_into_clauses.yml            # Clause splitter output
│   ├── analyze_clause.yml                # Per-clause risk analysis
│   ├── flag_high_risk.yml                # Deep high-risk analysis
│   ├── aggregate_risk_summary.yml        # Aggregated risk report
│   └── generate_executive_summary.yml    # Executive summary
└── tools/
    ├── __init__.py
    └── contract_reviewer/
        ├── __init__.py
        ├── split_contract_by_clause.py   # MAP: split contract into clauses
        └── aggregate_clause_analyses.py  # REDUCE: aggregate clause analyses
```

## Running the Workflow

```bash
# 1. Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys

# 2. Run the workflow
agac run -a contract_reviewer

# 3. Results appear in agent_io/target/ per action
```

## Output

The workflow produces:

1. **Per-clause analyses** with risk level, obligations, and deadlines
2. **Deep analysis** of high-risk clauses with negotiation points
3. **Aggregated risk report** with overall risk level and distribution
4. **Executive summary** with verdict, top concerns, and next steps

## Customization

- **Risk criteria**: Modify `seed_data/risk_criteria.json` to adjust risk indicators
- **Clause splitting**: Update regex patterns in `split_contract_by_clause.py` for different formats
- **Risk threshold**: Change the guard condition to filter on different risk levels
- **Models**: Swap model vendors in the workflow YAML to use different LLMs
- **Aggregation logic**: Adjust risk scoring weights in `aggregate_clause_analyses.py`
