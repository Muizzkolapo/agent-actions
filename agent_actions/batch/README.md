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

### Batch Submission During Workflow

When you run a workflow containing batch agents:

```bash
agent-actions run -a my_workflow
```

The system automatically:

1. **Prepares batch tasks** from staging or target processor data
2. **Loads schema** using the configured `schema_name`
3. **Creates batch input file** (`{agent_type}_batch_input.jsonl`)
4. **Submits job** to OpenAI Batch API
5. **Creates placeholder files** in the workflow output directory structure
6. **Continues workflow** with subsequent agents

### Batch Continuation

To continue the workflow after batch jobs complete:

```bash
agent-actions run -a my_workflow --batch_continue
```

This command:

1. **Checks all batch jobs** for completion status
2. **Processes completed results** into workflow output directories
3. **Converts batch responses** to workflow-compatible format
4. **Continues normal workflow** execution

## Directory Structure

Batch processing integrates seamlessly with the existing workflow directory structure:

```
my_agent/
├── agent_io/
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

### Batch Management Commands

#### Check Batch Status

```bash
# Check last submitted batch job
agent-actions batch status

# Check specific batch job
agent-actions batch status --batch-id <batch_id>
```

#### Retrieve Batch Results

```bash
# Retrieve last batch job results
agent-actions batch retrieve

# Retrieve specific batch job results
agent-actions batch retrieve --batch-id <batch_id> --output-dir ./results
```

### Workflow Commands

#### Standard Workflow Run

```bash
agent-actions run -a my_workflow
```

#### Batch Continuation Run

```bash
agent-actions run -a my_workflow --batch_continue
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

Monitor batch job progress:

```bash
# Check status periodically
agent-actions batch status

# Continue workflow when ready
agent-actions run -a my_workflow --batch_continue
```

### 4. Error Handling

The system handles common batch processing issues:

- **Invalid JSON responses** are captured with error metadata
- **Failed batch items** are logged but don't stop processing
- **Incomplete batches** can be resubmitted after investigation

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
2. **Batch job failed**: Check OpenAI API limits and model availability
3. **No results processed**: Verify batch job completion before using `--batch_continue`
4. **Directory not found**: Ensure agent directory structure exists

### Debug Commands

```bash
# Check batch job details
agent-actions batch status --batch-id <batch_id>

# Verify schema loading
agent-actions render -a my_workflow  # Check schema references

# Check workflow structure
ls -la my_agent/agent_io/target/
```