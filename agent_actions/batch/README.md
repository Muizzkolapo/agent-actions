# Batch Processing with Agent Actions

This document explains how the batch processing feature works in the Agent Actions CLI, including all touchpoints for future improvements.

## Overview

The batch processing feature allows you to run agent actions on large datasets asynchronously using the OpenAI Batch API. This is useful for tasks such as data enrichment, content generation, and sentiment analysis where you need to process thousands of items cost-effectively.

The batch processing workflow is seamlessly integrated into the main `run` command and workflow system. When agents are configured for batch processing, the system automatically handles job submission, status checking, and result processing into the same directory structure as regular workflows.

## Architecture Overview

### Key Components

1. **BatchService** (`agent_actions/services/batch_service.py`)
   - Core batch processing logic
   - OpenAI Batch API integration
   - Result processing and transformation
   - Registry management for multi-file processing

2. **AgentWorkflow** (`agent_actions/workflow/agent_workflow.py`)
   - Workflow orchestration
   - Batch status checking
   - State management integration

3. **Batch Registry** (`.batch_registry.json`)
   - Tracks multiple batch jobs per agent
   - Maintains file-to-batch mapping
   - Stores job status and timestamps

4. **Agent Status** (`.agent_status.json`)
   - Tracks overall agent completion state
   - No longer stores individual batch IDs

## Multi-File Processing Architecture

### Registry-Based Tracking System

The system now supports processing multiple files per agent using a registry-based approach:

```json
{
  "file1.json": {
    "batch_id": "batch_123",
    "status": "completed",
    "timestamp": "2024-01-15T10:30:00"
  },
  "file2.json": {
    "batch_id": "batch_456", 
    "status": "in_progress",
    "timestamp": "2024-01-15T10:31:00"
  }
}
```

### Status Flow

1. **Individual Files** → **Individual Batch Jobs** → **Registry Tracking**
2. **All Jobs Complete** → **Registry Status = 'completed'** → **Processing Begins**
3. **File-to-File Mapping** → **Individual Output Files** → **Transformation Applied**

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

1. **Submit batch jobs** for each file if they haven't been submitted already
2. **Update the workflow status** to `batch_submitted`
3. **Exit** and instruct you to run the command again to check the status

When you run the same command again:

```bash
agent-actions run -a my_workflow
```

The system will:

1. **Check the status** of ALL batch jobs in the registry
2. If ALL jobs are **complete**, it will download and process ALL results, maintaining file-to-file mapping
3. If ANY job is **still running**, it will report the status and exit

This creates a seamless experience where the same command is used to initiate, monitor, and continue the workflow.

## Directory Structure

Batch processing integrates seamlessly with the existing workflow directory structure:

```
my_agent/
├── agent_io/
│   ├── .agent_status.json        # Workflow state file (no batch IDs)
│   ├── staging/                  # Initial input files
│   │   ├── file1.json
│   │   └── file2.json
│   ├── target/
│   │   ├── node_0_staging_agent/   # Staging output
│   │   ├── node_1_batch_agent/     # Batch results (after completion)
│   │   │   ├── file1.json          # Processed results from file1.json
│   │   │   ├── file2.json          # Processed results from file2.json
│   │   │   └── batch/              # Batch job tracking
│   │   │       ├── .batch_registry.json
│   │   │       ├── batch_123_results.jsonl
│   │   │       └── batch_456_results.jsonl
│   │   └── node_2_final_agent/     # Final processing
│   └── source/                     # Source content tracking
├── agent_config/
└── batch/                          # Legacy batch job files
    ├── batch_agent_batch_input.jsonl
    └── .last_batch_id
```

## Key Code Touchpoints for Future Improvements

### 1. BatchService Class (`agent_actions/services/batch_service.py`)

#### Key Methods:
- `_save_batch_job_id()` - Lines 241-272: Registry creation and management
- `_get_batch_registry_status()` - Lines 322-370: Overall status checking
- `_are_all_batch_jobs_completed()` - Lines 304-350: Individual job completion checking
- `process_all_batch_results_to_workflow_output()` - Lines 801-908: Multi-file processing with file-to-file mapping

#### Future Improvement Areas:
- **Retry Logic**: Add retry mechanisms for failed batch jobs
- **Partial Processing**: Handle scenarios where some jobs fail but others succeed
- **Performance**: Optimize API calls when checking multiple batch statuses
- **Cleanup**: Add methods to clean up old batch files and registries

### 2. AgentWorkflow Class (`agent_actions/workflow/agent_workflow.py`)

#### Key Methods:
- `_handle_batch_agent()` - Lines 145-172: Registry-based status checking
- `_process_all_batch_results()` - Lines 174-180: Simplified processing call
- `_update_status()` - Lines 139-143: Removed batch_id tracking

#### Future Improvement Areas:
- **Progress Reporting**: Add detailed progress reporting for multi-file processing
- **Parallel Processing**: Process multiple completed batch jobs in parallel
- **Error Recovery**: Better handling of partial failures
- **Notifications**: Add webhook or email notifications for batch completion

### 3. Batch Registry System

#### Registry Structure:
```json
{
  "file_name": {
    "batch_id": "string",
    "status": "submitted|in_progress|completed|failed", 
    "timestamp": "ISO_timestamp"
  }
}
```

#### Future Improvement Areas:
- **Metadata**: Add more metadata like file size, processing time, error details
- **Versioning**: Add registry format versioning for backward compatibility
- **Compression**: Compress large registry files
- **Backup**: Implement registry backup and recovery mechanisms

### 4. Data Transformation Pipeline

#### Key Methods:
- `_convert_batch_results_to_workflow_format()` - Lines 582-669: Result transformation
- `_separate_side_output()` - Lines 65-74: Side output handling
- `DataTransformer.transform_structure()` - External class for data transformation

#### Future Improvement Areas:
- **Streaming**: Process large result sets in streaming fashion
- **Validation**: Add result validation before transformation
- **Caching**: Cache transformed results for recovery scenarios
- **Metrics**: Add processing metrics and performance tracking

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

### Batch-Specific Commands

#### `batch status`

Check the status of batch jobs (uses backward compatibility method).

```bash
agent-actions batch status --batch-id batch_123
```

#### `batch retrieve`

Retrieve batch results (uses backward compatibility method).

```bash
agent-actions batch retrieve --batch-id batch_123 --output-dir ./results
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

### 3. File Organization

Organize input files properly for batch processing:

```
staging/
├── batch_001.json    # Will create batch_001.json in output
├── batch_002.json    # Will create batch_002.json in output
└── batch_003.json    # Will create batch_003.json in output
```

### 4. Batch Job Monitoring

Monitor batch job progress using the `status` command:

```bash
# Check status periodically
agent-actions status -a my_workflow

# Continue workflow when ready by running the run command again
agent-actions run -a my_workflow
```

### 5. Error Handling

The system handles common batch processing issues:

- **Invalid JSON responses** are captured with error metadata
- **Failed batch items** are logged but don't stop processing
- **Failed batch jobs** will be marked as `failed` in the registry
- **Partial failures** allow successful jobs to continue processing

## Integration with Existing Workflows

Batch processing works seamlessly with existing agent workflows:

1. **Staging agents** can feed data to batch agents
2. **Batch agents** output to the same directory structure with file-to-file mapping
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
4. **Registry corruption**: Delete `.batch_registry.json` and restart the workflow
5. **Partial processing**: Check individual batch job statuses in the registry

### Debug Commands

```bash
# Check workflow status
agent-actions status -a my_workflow

# Verify schema loading
agent-actions render -a my_workflow  # Check schema references

# Check workflow structure
ls -la my_agent/agent_io/target/

# Inspect batch registry
cat my_agent/agent_io/target/node_X_batch_agent/batch/.batch_registry.json

# Check individual batch results
ls -la my_agent/agent_io/target/node_X_batch_agent/batch/batch_*_results.jsonl
```

## Future Development Areas

### High Priority
1. **Retry Mechanisms**: Implement automatic retry for failed batch jobs
2. **Progress Tracking**: Add detailed progress reporting for multi-file processing
3. **Performance Optimization**: Optimize API calls and result processing
4. **Error Recovery**: Better handling of partial failures and recovery scenarios

### Medium Priority
1. **Parallel Processing**: Process multiple completed batch jobs in parallel
2. **Streaming Results**: Handle very large result sets efficiently
3. **Metrics and Monitoring**: Add comprehensive metrics and monitoring
4. **Notification System**: Add webhook or email notifications for batch completion

### Low Priority
1. **Registry Backup**: Implement registry backup and recovery mechanisms
2. **Compression**: Compress large registry and result files
3. **Versioning**: Add registry format versioning for backward compatibility
4. **Cleanup Tools**: Add tools to clean up old batch files and registries

## Contributing

When making changes to the batch processing system:

1. **Test with multiple files**: Always test with multiple input files to ensure file-to-file mapping works
2. **Check registry integrity**: Ensure registry updates are atomic and don't corrupt existing data
3. **Backward compatibility**: Maintain compatibility with existing workflows and CLI commands
4. **Error handling**: Add proper error handling and logging for debugging
5. **Documentation**: Update this documentation with any architectural changes