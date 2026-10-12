# Contract Reviewer

<p align="center"><img src="docs/flow.png" width="700"/></p>

## What You'll Learn

This is the **only example** in the repository that demonstrates the **Map-Reduce pattern** and **FILE granularity**. You'll learn how to:

- **Split one input record into many** (the "map" step) using a Tool action that returns a list.
- **Process each fragment independently** with per-record LLM actions.
- **Collect all fragments back into one** (the "reduce" step) using a Tool action with `granularity: File`, which receives every record from the file at once instead of one at a time.

---

## The Problem

A legal team needs to review contracts before signing. Each contract contains many clauses -- payment, IP, liability, termination -- and each clause carries different risk. Reviewing a whole contract in a single LLM call works poorly. The model loses focus. The output is unstructured. And you can't selectively deep-dive into the dangerous parts.

The Map-Reduce pattern solves this naturally:

1. **Map** -- split the contract into individual clauses so each one is analyzed in isolation with full attention.
2. **Process** -- run each clause through a risk-analysis prompt that scores it against seed-data criteria.
3. **Reduce** -- aggregate all clause-level results into a single contract-level risk report.
4. **Summarize** -- generate a plain-language executive summary from the aggregated report.

---

## How It Works

The workflow contains four actions executed in sequence. Here's what each one does and which YAML settings matter.

### 1. `split_into_clauses` (Tool)

Parses the contract's `full_text` field and emits **one record per clause**. One contract goes in, N clause records come out.

- **Kind**: `tool` -- Python function, no LLM call.
- **Impl**: `split_contract_by_clause` -- regex finds numbered headings (`1. DEFINITIONS`, `Section 2: ...`, etc.) and slices the text.
- **Output fields**: `clause_number`, `clause_title`, `clause_text`
- **Context scope**: observes only `source.full_text`, `source.contract_id`, and `source.title`; passes through metadata (`contract_id`, `title`, `parties`) so downstream actions can reference the contract.

### 2. `analyze_clause` (LLM / Gemini)

Analyzes **each** clause against the risk criteria from seed data. The default granularity is `Record`, so the framework invokes this action once per clause.

- **Model**: `gemini-flash-lite-latest` via Gemini (the workflow default); the config has a commented-out option to switch to `claude-sonnet-4-20250514` via Anthropic for stronger legal reasoning.
- **Prompt**: classify risk as high/medium/low, extract obligations and deadlines, recommend an action (accept, negotiate, reject, or flag_for_legal).
- **Seed data**: `risk_criteria.json` is injected through `context_scope.observe`, giving the model a rubric with concrete indicators for each risk level.
- **Output fields**: `risk_level`, `risk_score`, `risk_indicators`, `obligations`, `deadlines`, `reasoning`, `recommended_action`

### 3. `aggregate_risk_summary` (Tool, FILE granularity)

The reduce step. Collects **all** clause-level analyses into a single contract-level risk report. FILE granularity is essential here -- without it, the framework passes records one at a time and the tool can't compute cross-clause aggregates.

- **Kind**: `tool` -- Python function.
- **Granularity**: `File` -- input is a `list[dict]` of every record, not a single record.
- **Impl**: `aggregate_clause_analyses` -- counts risk levels, computes average risk scores, collects obligations and deadlines, builds a prioritized negotiation list.
- **Output fields**: `overall_risk_level`, `overall_risk_score`, `risk_distribution`, `high_risk_clauses`, `total_obligations`, `key_deadlines`, `negotiation_priority`

### 4. `generate_executive_summary` (LLM / Gemini)

Plain-language summary for VP/C-level stakeholders. It deliberately **doesn't** see individual clause analyses -- only the aggregated report -- keeping context tight.

- **Model**: `gemini-flash-lite-latest` via Gemini (the workflow default).
- **Context scope**: observes only `aggregate_risk_summary.*`; explicitly drops `analyze_clause.*` and `split_into_clauses.*`.
- **Output fields**: `executive_summary`, `risk_verdict`, `top_concerns`, `recommended_next_steps`, `approval_conditions`, `estimated_negotiation_effort`

---

## Key Patterns Explained

### Map-Reduce Pattern

Split a large document into pieces, process each piece independently, then combine the results. In AGAC: a Tool action returns a list (the map step), normal per-record actions process each element, and a `granularity: File` action merges everything back (the reduce step).

**Map step** -- the tool returns a Python `list[dict]`, and the framework automatically fans out one record per list element:

```yaml
- name: split_into_clauses
  kind: tool
  impl: split_contract_by_clause
  intent: "Split contract full_text into individual numbered clauses"
  schema: split_into_clauses
  context_scope:
    observe:
      - source.full_text
      - source.contract_id
      - source.title
    passthrough:
      - source.contract_id
      - source.title
      - source.parties
```

After this action, the workflow has N records (one per clause) where before it had 1. Every subsequent action (until the reduce step) runs once per clause.

**Reduce step** -- the `granularity: File` setting tells the framework to batch all records from the same file back into a single call:

```yaml
- name: aggregate_risk_summary
  dependencies: [analyze_clause]
  kind: tool
  impl: aggregate_clause_analyses
  intent: "Aggregate all clause analyses into a unified contract risk report"
  schema: aggregate_risk_summary
  granularity: File
  context_scope:
    observe:
      - analyze_clause.*
      - split_into_clauses.clause_number
      - split_into_clauses.clause_title
      - source.contract_id
      - source.title
      - source.parties
```

### FILE Granularity

By default, every action uses `granularity: Record` -- one record at a time. Set `granularity: File`, and the action receives **all records from the input file in a single call**.

This matters whenever your logic needs a cross-record view: computing averages, counting distributions, sorting by priority, producing one output from many inputs. Without it, the aggregation tool would see one clause at a time and could never build a contract-level summary.

A FILE granularity tool in Python receives a `list[dict]`, one item per record, holding the observed fields as flat keys. The one wildcard's fields are bare (`risk_level`); the fields named one by one beside it carry their action's name (`split_into_clauses.clause_title`, `source.contract_id`). A tool that builds a new row returns a `FileUDFResult`:

```python
from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.types import Granularity

@udf_tool(granularity=Granularity.FILE)
def aggregate_clause_analyses(data: list[dict[str, Any]]) -> FileUDFResult:
    # data contains ALL clause records at once
    contract_id = data[0].get("source.contract_id", "unknown")
    high = [r for r in data if r.get("risk_level") == "high"]
    # ... aggregate logic ...
    # source_index: None — no single input produced this row
    return FileUDFResult(outputs=[{"source_index": None, "data": single_summary_dict}])
```

The framework handles all metadata propagation (`source_guid`, lineage) automatically — tools just return business data.

### Retry and Expectations

All LLM actions inherit retry from defaults -- transient API errors (rate limits, timeouts) are retried up to 2 times with backoff:

```yaml
defaults:
  retry:
    enabled: true
    max_attempts: 2
```

`analyze_clause` also carries an expectation. If the LLM returns null values for `risk_score` or other required fields, the block fails and the framework regenerates automatically:

```yaml
expect:
  max_iterations: 2
  expectations:
    - { type: no_null_fields }
```

`no_null_fields` is a built-in record-scoped rule: it checks every field of the
record at once rather than one named field, so it needs no field list. The
repair policy and `on_exhausted` come from the workflow's `defaults.expect`.

---

## Quick Start

Install the CLI:

```bash
pip install agent-actions-cli
```

Copy the environment sample and fill in your API keys:

```bash
cp .env.sample .env
# Edit .env with your GEMINI_API_KEY
```

Run the workflow:

```bash
agac run -a contract_reviewer
```

By default the workflow processes 2 records (`record_limit: 2` in the config). Remove or increase that setting to process the full dataset.

The sample input (`agent_io/staging/contracts.json`) includes three contracts of varying risk levels. After the run completes, check the output database for per-clause analyses, aggregated risk summaries, and executive summaries.

---

## Project Structure

```
contract_reviewer/
├── README.md
├── docs/
├── agent_actions.yml
├── agent_workflow/
│   └── contract_reviewer/
│       ├── agent_config/
│       │   └── contract_reviewer.yml
│       ├── agent_io/
│       │   ├── staging/
│       │   │   └── contracts.json
│       │   └── target/
│       └── seed_data/
│           └── risk_criteria.json
├── prompt_store/
│   └── contract_reviewer.md
├── schema/
│   └── contract_reviewer/
│       ├── split_into_clauses.yml
│       ├── analyze_clause.yml
│       ├── aggregate_risk_summary.yml
│       └── generate_executive_summary.yml
└── tools/
    └── contract_reviewer/
        ├── split_contract_by_clause.py
        └── aggregate_clause_analyses.py
```
