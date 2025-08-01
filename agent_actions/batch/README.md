# Batch Processing with Agent Actions

This document explains how the batch processing feature works in the Agent Actions CLI, including all touchpoints for future improvements.

## Overview

The batch processing feature allows you to run agent actions on large datasets asynchronously using multiple provider APIs (OpenAI, Gemini, Anthropic). This is useful for tasks such as data enrichment, content generation, and sentiment analysis where you need to process thousands of items cost-effectively.

The batch processing workflow is seamlessly integrated into the main `run` command and workflow system. When agents are configured for batch processing, the system automatically handles job submission, status checking, and result processing using a **registry-based tracking system** that maintains file-to-batch job mappings within each workflow's directory structure.

## Architecture Overview

### Key Components

1. **BatchService** (`agent_actions/services/batch_service.py`)
   - Core batch processing logic
   - Multi-provider batch API integration (OpenAI, Gemini, Anthropic)
   - Result processing and transformation
   - Registry-based tracking system for multi-file processing

2. **AgentWorkflow** (`agent_actions/workflow/agent_workflow.py`)
   - Workflow orchestration
   - Batch status checking
   - State management integration

3. **Batch Registry** (`.batch_registry.json`)
   - **Primary tracking system** - no global files used
   - Tracks multiple batch jobs per agent within workflow directory
   - Maintains file-to-batch mapping with full isolation
   - Stores job status, timestamps, and provider information

4. **Agent Status** (`.agent_status.json`)
   - Tracks overall agent completion state
   - **No batch ID storage** - all tracking delegated to registry system

## Multi-File Processing Architecture

### Registry-Based Tracking System

The system uses **exclusively registry-based tracking** with no global files. Each workflow maintains its own isolated batch registry:

```json
{
  "file1.json": {
    "batch_id": "batch_123",
    "status": "completed",
    "timestamp": "2024-01-15T10:30:00",
    "provider": "openai"
  },
  "file2.json": {
    "batch_id": "batch_456", 
    "status": "in_progress",
    "timestamp": "2024-01-15T10:31:00",
    "provider": "anthropic"
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
    model_vendor: "openai"          # Unified provider field
    model_name: "gpt-4o-mini"
    schema_name: "my_output_schema"
    prompt: "Process the following content: {content}"
    ephemeral: false
```

### Required Configuration Fields

- `run_mode: batch` - Enables batch processing mode
- `model_vendor` - Provider to use: `"openai"`, `"gemini"`, or `"anthropic"`
- `schema_name` - References a schema file for structured JSON output
- `model_name` - Model to use (must be batch API compatible for the provider)
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
└── batch/                          # Legacy files (deprecated - registry system preferred)
    └── batch_agent_batch_input.jsonl
```

## Key Code Touchpoints for Future Improvements

### 1. BatchService Class (`agent_actions/services/batch_service.py`)

#### Key Registry Methods:
- `_save_batch_job_id()` - Registry creation and management (no global files)
- `_get_batch_registry_status()` - Overall status checking from registry
- `_get_batch_job_id_for_file()` - File-specific batch ID lookup
- `_update_batch_registry_status()` - Status updates within registry
- `process_all_batch_results_to_workflow_output()` - Multi-file processing with file-to-file mapping

#### Future Improvement Areas:
- **Retry Logic**: Add retry mechanisms for failed batch jobs
- **Partial Processing**: Handle scenarios where some jobs fail but others succeed
- **Performance**: Optimize API calls when checking multiple batch statuses
- **Multi-Provider Optimization**: Batch status checks across different providers
- **Registry Maintenance**: Add methods to clean up old registries and orphaned jobs

### 2. AgentWorkflow Class (`agent_actions/workflow/agent_workflow.py`)

#### Key Methods:
- `_handle_batch_agent()` - Registry-based status checking (no global file dependencies)
- `_process_all_batch_results()` - Simplified processing call using registry
- `_update_status()` - Status management without batch_id tracking

#### Future Improvement Areas:
- **Progress Reporting**: Add detailed progress reporting for multi-file processing
- **Parallel Processing**: Process multiple completed batch jobs in parallel
- **Error Recovery**: Better handling of partial failures
- **Notifications**: Add webhook or email notifications for batch completion

### 3. Batch Registry System

#### Registry Structure (Per-Workflow Isolation):
```json
{
  "file_name": {
    "batch_id": "string",
    "status": "submitted|in_progress|completed|failed", 
    "timestamp": "ISO_timestamp",
    "provider": "openai|gemini|anthropic"
  }
}
```

#### Future Improvement Areas:
- **Enhanced Metadata**: Add file size, processing time, error details, retry counts
- **Registry Versioning**: Add format versioning for backward compatibility
- **Performance**: Compress large registry files, optimize concurrent access
- **Cross-Provider**: Support mixed provider workflows within single registry
- **Backup & Recovery**: Implement registry backup and recovery mechanisms

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

Check the status of batch jobs (uses registry-based lookup when no batch-id provided).

```bash
agent-actions batch status --batch-id batch_123
# or auto-detect from registry:
agent-actions batch status
```

#### `batch retrieve`

Retrieve batch results (uses registry-based lookup when no batch-id provided).

```bash
agent-actions batch retrieve --batch-id batch_123 --output-dir ./results
# or auto-detect from registry:
agent-actions batch retrieve --output-dir ./results
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

Monitor batch job progress using the `status` command (all tracking via registry):

```bash
# Check workflow status (includes registry-based batch status)
agent-actions status -a my_workflow

# Continue workflow when ready
agent-actions run -a my_workflow

# Check specific batch job status
agent-actions batch status --batch-id batch_123
```

### 5. Error Handling

The registry-based system provides robust error handling:

- **Invalid JSON responses** are captured with error metadata in registry
- **Failed batch items** are logged with full context in registry
- **Failed batch jobs** are marked as `failed` with provider info in registry
- **Partial failures** allow successful jobs to continue processing
- **Registry corruption** is detected and can be recovered
- **Cross-provider errors** are handled independently per job

## Integration with Existing Workflows

Batch processing works seamlessly with existing agent workflows:

1. **Staging agents** can feed data to batch agents
2. **Batch agents** output to the same directory structure with file-to-file mapping
3. **Target agents** can process batch results further
4. **Output processor** handles batch results like regular data

## Cost Optimization

Batch processing provides significant cost savings across all providers:

- **50% cost reduction** compared to real-time API calls (OpenAI, Gemini, Anthropic)
- **Efficient processing** of large datasets with provider optimization
- **Registry-based tracking** eliminates duplicate job submissions
- **Multi-provider support** allows cost-optimal provider selection
- **Structured output** ensures consistent data quality across providers

## Troubleshooting

### Common Issues

1. **Schema not found**: Ensure schema files exist in the schema directory
2. **Batch job failed**: Check API limits and model availability for your provider. Run `agent status` to see the failed state.
3. **Directory not found**: Ensure agent directory structure exists
4. **Registry corruption**: Delete `.batch_registry.json` and restart the workflow
5. **Partial processing**: Check individual batch job statuses in the registry
6. **Provider mismatch**: Verify `model_vendor` matches the intended provider
7. **Legacy global files**: Remove any old `.last_batch_id` files - registry system is primary

### Debug Commands

```bash
# Check workflow status (registry-based)
agent-actions status -a my_workflow

# Verify schema loading
agent-actions render -a my_workflow  # Check schema references

# Check workflow structure
ls -la my_agent/agent_io/target/

# Inspect batch registry (primary tracking system)
cat my_agent/agent_io/target/node_X_batch_agent/batch/.batch_registry.json

# Check individual batch results
ls -la my_agent/agent_io/target/node_X_batch_agent/batch/batch_*_results.jsonl

# Verify no legacy global files exist
ls -la batch/.last_batch_id 2>/dev/null || echo "✅ No legacy global files"
```

## Future Development Areas

### High Priority
1. **Retry Mechanisms**: Implement automatic retry for failed batch jobs across providers
2. **Progress Tracking**: Add detailed progress reporting for multi-file, multi-provider processing
3. **Performance Optimization**: Optimize API calls and result processing per provider
4. **Cross-Provider Management**: Advanced scheduling and load balancing across providers

### Medium Priority
1. **Parallel Processing**: Process multiple completed batch jobs in parallel across providers
2. **Streaming Results**: Handle very large result sets efficiently
3. **Provider Analytics**: Add comprehensive metrics and monitoring per provider
4. **Smart Notifications**: Add webhook or email notifications with provider-specific insights

### Low Priority
1. **Registry Backup**: Implement registry backup and recovery mechanisms
2. **Compression**: Compress large registry and result files
3. **Registry Versioning**: Add registry format versioning for backward compatibility
4. **Maintenance Tools**: Add tools to clean up old registries and migrate legacy global files

## Contributing

When making changes to the batch processing system:

1. **Test with multiple files**: Always test with multiple input files to ensure file-to-file mapping works
2. **Registry integrity**: Ensure registry updates are atomic and don't corrupt existing data
3. **Provider compatibility**: Test across all supported providers (OpenAI, Gemini, Anthropic)
4. **No global dependencies**: Never add global file dependencies - use registry system only
5. **Cross-provider isolation**: Ensure different provider jobs don't interfere with each other
6. **Error handling**: Add proper error handling and logging for debugging
7. **Documentation**: Update this documentation with any architectural changes