# Batch Processing with Agent Actions

This document explains how to use the batch processing feature of the Agent Actions CLI.

## Overview

The batch processing feature allows you to run agent actions on large datasets asynchronously using the OpenAI Batch API. This is useful for tasks such as data enrichment, content generation, and sentiment analysis where you need to process thousands of items cost-effectively.

The batch processing workflow is seamlessly integrated into the main `run` command and workflow system. When agents are configured for batch processing, the system automatically handles job submission, status checking, and result processing into the same directory structure as regular workflows.

## Configuration

To use batch processing, configure your agent with `run_mode: batch` and ensure it has a schema defined for structured output.

### Example Agent Configuration

```yaml
my_batch_agent:
  - agent_type: my_agent
    run_mode: batch
    model_name: "gpt-4o-mini"
    schema_name: "my_output_schema"
    prompt: "Process the following content: {content}"
    ephemeral: false
```

### Required Configuration Fields

- `run_mode: batch` - Enables batch processing mode
- `schema_name` - References a schema file for structured JSON output
- `model_name` - OpenAI model to use (batch API compatible models)
- `prompt` - Template with placeholders for data processing

## Workflow Integration

### State-Aware Workflow

The `agent run` command is now state-aware and idempotent. It automatically manages the workflow state, including batch jobs, without requiring special flags.

When you run a workflow containing a batch agent:

```bash
agent-actions run -a my_workflow
```

The system will:

1.  **Submit the batch job** if it hasn't been submitted already.
2.  **Update the workflow status** to `batch_submitted`.
3.  **Exit** and instruct you to run the command again to check the status.

When you run the same command again:

```bash
agent-actions run -a my_workflow
```

The system will:

1.  **Check the status** of the in-flight batch job.
2.  If the job is **complete**, it will download the results and **continue the workflow** from where it left off.
3.  If the job is **still running**, it will report the status and exit.

This creates a seamless experience where the same command is used to initiate, monitor, and continue the workflow.

## Directory Structure

Batch processing integrates seamlessly with the existing workflow directory structure:

```
my_agent/
├── agent_io/
│   ├── .agent_status.json        # Workflow state file
│   ├── staging/                    # Initial input files
│   ├── target/
│   │   ├── node_0_staging_agent/   # Staging output
│   │   ├── node_1_batch_agent/     # Batch results (after completion)
│   │   └── node_2_final_agent/     # Final processing
│   └── source/                     # Source content tracking
├── agent_config/
└── batch/                          # Batch job files
    ├── batch_agent_batch_input.jsonl
    └── .last_batch_id
```

## Command Reference

### Workflow Commands

#### `agent run`

The primary command to execute a workflow. It is idempotent and state-aware.

```bash
agent-actions run -a my_workflow
```

#### `agent status`

A read-only command to check the current state of a workflow.

```bash
agent-actions status -a my_workflow
```

#### `agent clean`

Wipes the `agent_io` directory, including the status file, for a fresh run.

```bash
agent-actions clean -a my_workflow
```

## Best Practices

### 1. Schema Design

Define clear, structured schemas for consistent batch output:

```json
{
  "name": "content_analysis",
  "description": "Analyze content for sentiment and topics",
  "type": "object",
  "properties": {
    "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
    "topics": {"type": "array", "items": {"type": "string"}},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  },
  "required": ["sentiment", "topics", "confidence"]
}
```

### 2. Prompt Templates

Use clear placeholder syntax in prompts:

```yaml
prompt: |
  Analyze the following content for sentiment and key topics:
  
  Content: {content}
  
  Provide a structured analysis with sentiment classification and topic extraction.
```

### 3. Batch Job Monitoring

Monitor batch job progress using the `status` command:

```bash
# Check status periodically
agent-actions status -a my_workflow

# Continue workflow when ready by running the run command again
agent-actions run -a my_workflow
```

### 4. Error Handling

The system handles common batch processing issues:

- **Invalid JSON responses** are captured with error metadata
- **Failed batch items** are logged but don't stop processing
- **Failed batch jobs** will be marked as `failed` in the status file.

## Integration with Existing Workflows

Batch processing works seamlessly with existing agent workflows:

1. **Staging agents** can feed data to batch agents
2. **Batch agents** output to the same directory structure
3. **Target agents** can process batch results further
4. **Output processor** handles batch results like regular data

## Cost Optimization

Batch processing provides significant cost savings:

- **50% cost reduction** compared to real-time API calls
- **Efficient processing** of large datasets
- **Automatic job management** reduces manual oversight
- **Structured output** ensures consistent data quality

## Troubleshooting

### Common Issues

1. **Schema not found**: Ensure schema files exist in the schema directory
2. **Batch job failed**: Check OpenAI API limits and model availability. Run `agent status` to see the failed state.
3. **Directory not found**: Ensure agent directory structure exists

### Debug Commands

```bash
# Check workflow status
agent-actions status -a my_workflow

# Verify schema loading
agent-actions render -a my_workflow  # Check schema references

# Check workflow structure
ls -la my_agent/agent_io/target/
```