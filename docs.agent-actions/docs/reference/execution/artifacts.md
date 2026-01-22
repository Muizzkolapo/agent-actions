---
title: Artifacts & Run Tracking
sidebar_position: 3
---

# Artifacts & Run Tracking

What happens behind the scenes when your agentic workflow runs? Agent Actions generates a trail of artifacts - structured data that lets you debug failures, audit decisions, and resume interrupted runs.

Think of artifacts as your agentic workflow's flight recorder. Every action, every output, every decision is tracked and stored in a predictable structure.

## Directory Structure

Let's explore where everything lives:

```
project/
├── artefact/
│   ├── runs.json                    # Run history and metrics
│   └── rendered_workflows/          # Jinja2-rendered configs
│       └── my_workflow.yml
├── logs/
│   └── agent_actions.log            # Execution logs
└── agent_workflow/
    └── my_workflow/
        └── agent_io/
            ├── .agent_status.json   # Action status tracking
            ├── .upstream_manifest.json  # Upstream dependencies
            ├── staging/             # Input data (starting point)
            ├── source/              # Metadata tracking staging files
            └── target/              # Output data
                ├── node_0_action_name/
                └── node_1_action_name/
```

Each agentic workflow gets its own `agent_io` directory. Input data goes in `staging/`, the `source/` folder tracks metadata for lineage, and results are written to `target/`. The `artefact` directory at the project root tracks cross-workflow metrics.

## Run History (`artefact/runs.json`)

You might wonder: how do I track success rates over time? Or find out which agentic workflows are consuming the most tokens?

The `runs.json` file tracks all agentic workflow executions with metrics:

```json
{
  "metadata": {
    "generated_at": "2025-12-31T19:59:34",
    "total_runs": 34,
    "schema_version": "1.0"
  },
  "workflow_metrics": {
    "my_workflow": {
      "total_runs": 30,
      "successful_runs": 25,
      "failed_runs": 5,
      "total_tokens": 136373,
      "success_rate": 0.83,
      "avg_duration_seconds": 24.84
    }
  },
  "executions": [
    {
      "id": "run_my_workflow_034",
      "workflow_id": "my_workflow",
      "status": "SUCCESS",
      "started_at": "2025-12-31T19:59:34",
      "ended_at": "2025-12-31T19:59:35",
      "duration_seconds": 0.25,
      "total_actions": 7,
      "successful_actions": 7,
      "failed_actions": 0,
      "skipped_actions": 0,
      "total_tokens": 1500,
      "actions": {
        "extract_data": {
          "status": "success",
          "started_at": "...",
          "ended_at": "...",
          "duration_seconds": 0.025,
          "type": "llm"
        },
        "transform_data": {
          "status": "success",
          "type": "tool",
          "impl": "transform_function"
        }
      }
    }
  ]
}
```

### Workflow Metrics

| Field | Type | Description |
|-------|------|-------------|
| `total_runs` | integer | Total workflow executions |
| `successful_runs` | integer | Completed without errors |
| `failed_runs` | integer | Terminated with errors |
| `total_tokens` | integer | Cumulative LLM tokens used |
| `success_rate` | float | Success ratio (0.0-1.0) |
| `avg_duration_seconds` | float | Average run time |

### Execution Record

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique run identifier |
| `status` | string | `SUCCESS`, `FAILED`, `PARTIAL` |
| `total_actions` | integer | Actions in workflow |
| `successful_actions` | integer | Completed actions |
| `failed_actions` | integer | Failed actions |
| `skipped_actions` | integer | Guard-skipped actions |
| `actions` | object | Per-action execution details |

## Rendered Workflows (`artefact/rendered_workflows/`)

After Jinja2 template processing, the fully-rendered workflow YAML is saved for debugging:

```bash
# Original workflow with templates
agent_workflow/my_workflow/agent_config/my_workflow.yml

# Rendered output (templates expanded)
artefact/rendered_workflows/my_workflow.yml
```

Use this to verify template expansion and troubleshoot Jinja2 issues.

## Action Status (`.agent_status.json`)

Located in `agent_io/`, tracks per-action execution state:

```json
{
  "fact_extractor": {
    "status": "completed"
  },
  "canonicalize_facts": {
    "status": "completed"
  },
  "validate_output": {
    "status": "pending"
  }
}
```

### Status Values

| Status | Description |
|--------|-------------|
| `pending` | Not yet executed |
| `completed` | Successfully finished |
| `failed` | Terminated with error |
| `skipped` | Skipped by guard condition |

### Resumable Execution

Here's where it gets practical: Agent Actions uses `.agent_status.json` for resumable runs. If an agentic workflow fails partway through, re-running it skips completed actions and resumes from the failure point.

This means you don't lose work when something breaks. Fix the issue and run again - Agent Actions picks up where it left off.

## Upstream Manifest (`.upstream_manifest.json`)

When agentic workflows depend on each other, how does Agent Actions know where to find upstream data? The upstream manifest tracks the connection:

```json
{
  "upstream_workflow": "data_processor",
  "upstream_path": "/path/to/data_processor/agent_io/target/node_5_final_output",
  "files": [
    "processed_data.json"
  ]
}
```

This enables:
- Automatic data linking between agentic workflows
- Lineage tracking across pipeline stages
- Dependency resolution with the `--upstream` flag

## Node-Based Output Structure

Each action's output is stored in a numbered folder within `target/`:

```
target/
├── node_0_fact_extractor/
│   └── combined_scraped_sample.json
├── node_1_canonicalize_facts/
│   └── combined_scraped_sample.json
└── node_2_flatten_the_facts/
    └── combined_scraped_sample.json
```

**Node naming format:** `node_{index}_{action_name}`

The index corresponds to topological execution order, enabling:
- Easy debugging of intermediate outputs
- DAG visualization
- Selective re-execution

## Output Record Structure

Consider what a single output record looks like. Each record contains three layers of data - system metadata, LLM output, and passthrough fields:

```json
{
  "source_guid": "37812c37-80a2-596b-8747-8f93e7a34e7f",
  "content": {
    "candidate_facts_list": [
      {
        "fact": "Requests MUST include a string or integer ID",
        "quote": "The ID MUST NOT be null",
        "technical_level": "implementation"
      }
    ]
  },
  "target_id": "dd45e6ef-63d6-45f6-8759-5df33c9a84a2",
  "node_id": "node_0_86a1e066-9522-4e0e-a3db-e83c7e38ab8c",
  "lineage": [
    "node_0_86a1e066-9522-4e0e-a3db-e83c7e38ab8c"
  ]
}
```

### Record Fields

| Field | Type | Description |
|-------|------|-------------|
| `source_guid` | string | UUID linking to original source record |
| `content` | object | LLM output (schema-validated) |
| `target_id` | string | UUID for this output record |
| `node_id` | string | Action execution identifier (`node_{index}_{uuid}`) |
| `lineage` | array | Chain of node_ids from source to current |

### Data Layers

**1. Agent Actions Metadata**

System-generated tracking fields:

| Field | Purpose |
|-------|---------|
| `source_guid` | Links output back to original input record |
| `target_id` | Unique identifier for this output |
| `node_id` | Identifies which action execution produced this |
| `lineage` | Full DAG path for provenance tracking |

**2. LLM/Tool Output (`content`)**

The `content` field contains the schema-validated output from the action:

```json
"content": {
  "candidate_facts_list": [...],  // LLM output matching schema
  "reasoning": "...",              // Additional LLM fields
  "score": 85                      // Validated against schema
}
```

For tool actions, `content` contains the UDF return value.

**3. Passthrough Fields**

Fields from `context_scope.passthrough` are preserved at the root level:

```yaml
# Workflow config
context_scope:
  passthrough:
    - source.url
    - upstream_action.metadata
```

```json
// Output record
{
  "source_guid": "...",
  "content": { ... },
  "url": "https://example.com",        // Passthrough from source
  "metadata": { ... },                  // Passthrough from upstream
  "target_id": "...",
  "node_id": "...",
  "lineage": [...]
}
```

### Lineage Tracking

How do you trace a record back through its transformations? The `lineage` array grows as records flow through the DAG:

```json
// Node 0 (first action)
"lineage": ["node_0_abc123"]

// Node 5 (after 5 transformations)
"lineage": [
  "node_0_abc123",
  "node_1_def456",
  "node_2_ghi789_0",
  "node_3_jkl012_0",
  "node_4_mno345_0",
  "node_5_pqr678"
]
```

**Lineage suffixes:**
- No suffix: Standard execution
- `_0`, `_1`, etc.: Loop iteration index
- UUID portion: Unique execution ID

### Using Lineage for Debugging

Find all transformations for a record:

```bash
# Extract lineage from output
jq '.[0].lineage' target/node_5_validate/data.json

# Find intermediate states
for node in $(jq -r '.[0].lineage[]' target/node_5_validate/data.json); do
  echo "=== $node ==="
  find target -name "*.json" -path "*${node%_*}*" -exec jq '.[0].content' {} \;
done
```

### Token Usage & LLM Metadata

You might wonder: where are the token counts? LLM execution metadata (tokens, timing) is stored in `artefact/runs.json`, not in output records:

```json
// artefact/runs.json
{
  "executions": [{
    "actions": {
      "fact_extractor": {
        "status": "success",
        "duration_seconds": 2.5,
        "type": "llm"
      }
    },
    "total_tokens": 1500
  }]
}
```

This separation keeps output files clean for downstream processing while preserving full execution metrics for monitoring.

:::info
Output records are designed for data pipelines - they contain only the data you need. Operational metrics live separately in `runs.json`.
:::

## Logs (`logs/agent_actions.log`)

Detailed execution logs with configurable verbosity:

```
19:56:59.636 INFO     Starting agent-actions CLI
19:56:59.637 DEBUG    Creating project paths for agent: my_workflow
19:56:59.641 INFO     Starting render template
19:57:00.915 INFO     [9ed9e3e9] Checking upstream dependencies...
19:57:00.917 INFO     [9ed9e3e9] Workflow started (sync)
19:57:00.918 DEBUG    [9ed9e3e9] [extract_data] Agent execution starting
19:57:00.922 DEBUG    [9ed9e3e9] [extract_data] Preparing prompt...
19:57:00.927 DEBUG    [9ed9e3e9] [extract_data] Prompt preparation complete
```

### Log Format

| Component | Description |
|-----------|-------------|
| Timestamp | `HH:MM:SS.ms` format |
| Level | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| Run ID | `[9ed9e3e9]` - Unique execution identifier |
| Action | `[action_name]` - Current action context |
| Message | Detailed operation description |

### Environment Variables

```bash
AGENT_ACTIONS_LOG_LEVEL=DEBUG     # Set log verbosity
AGENT_ACTIONS_LOG_FILE=custom.log # Custom log path
AGENT_ACTIONS_NO_LOG_FILE=1       # Disable file logging
```

## Staging Directory (`agent_io/staging/`)

When agentic workflows connect, where does the handoff happen? The staging directory serves as intermediate storage for cross-workflow data:

```
agent_io/
├── staging/          # Input data (starting point, or data from upstream)
│   └── data.json     # Your input files go here
├── source/           # Metadata tracking staging files
└── target/           # Agentic workflow output
```

When using `--upstream`, data from the upstream agentic workflow's target is automatically linked to the downstream workflow's staging directory. You don't need to manually copy files - Agent Actions handles the wiring.

## Best Practices

### 1. Use Runs History for Monitoring

```bash
# Check agentic workflow health
jq '.workflow_metrics.my_workflow.success_rate' artefact/runs.json
```

### 2. Debug with Rendered Workflows

When Jinja2 templates aren't expanding as expected, compare the original with the rendered output:

```bash
# Compare original vs rendered
diff agent_workflow/my_workflow/agent_config/my_workflow.yml \
     artefact/rendered_workflows/my_workflow.yml
```

### 3. Inspect Intermediate Outputs

```bash
# Check specific node output
cat agent_io/target/node_2_transform_data/data.json | jq .
```

### 4. Resume Failed Runs

```bash
# After fixing issue, re-run to resume from failure point
agac run -a my_workflow
# Skips completed actions based on .agent_status.json
```

### 5. Track Token Usage

```bash
# Get total tokens across all runs
jq '[.executions[].total_tokens] | add' artefact/runs.json
```

:::tip
Run these commands regularly to monitor your agentic workflows. Token usage trends can reveal optimization opportunities.
:::
