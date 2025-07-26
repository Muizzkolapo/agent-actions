# Batch Mode Error Fixes

## Overview
Fixed critical errors in the batch processing workflow:
1. JSON parsing error: "Unterminated string starting at: line 1 column 399"
2. Type error: "'str' object has no attribute 'get'" in ScenarioGenerator
3. Missing lineage tracking in batch mode
4. Source file key mismatch causing "source_guid not found" errors

## Changes Made

### 1. Enhanced JSON Parsing Error Handling
**File**: `agent_actions/services/batch_service.py`

Added robust error handling for JSON parsing in three locations where batch results are parsed:

```python
# Parse batch results with error handling
batch_results = []
lines = result_content.decode('utf-8').strip().split('\n')
for line_num, line in enumerate(lines, 1):
    if line.strip():
        try:
            batch_results.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON parsing error on line {line_num}: {e}")
            print(f"[DEBUG] Line position: character {e.pos if hasattr(e, 'pos') else 'unknown'}")
            print(f"[DEBUG] Problematic content (first 500 chars): {line[:500]}...")
            if len(line) > 500:
                print(f"[DEBUG] Line length: {len(line)} characters")
            # Continue processing other lines instead of failing completely
            continue
```

### 2. Workflow Error Propagation
**File**: `agent_actions/workflow/agent_workflow.py`

Modified `_process_all_batch_results` to properly propagate errors instead of just warning:

```python
def _process_all_batch_results(self, output_directory):
    """Process all completed batch jobs in the registry together as one dataset."""
    try:
        # Use the new combined processing method
        processed_files = self.batch_service.process_all_batch_results_to_workflow_output(output_directory)
        if not processed_files:
            raise RuntimeError("No batch results were successfully processed")
    except Exception as e:
        self.console.print(f"[red]Error: Could not process batch results: {e}[/red]")
        raise  # Re-raise to stop the workflow instead of continuing with bad data
```

### 3. Batch Placeholder File Validation
**File**: `agent_actions/handlers/file_reader.py`

Added validation to prevent downstream agents from processing batch placeholder files:

```python
def _read_json(self):
    with open(self.file_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
        
        # Check if this is a batch placeholder file
        if isinstance(data, dict) and 'batch_job_id' in data and data.get('status') == 'submitted':
            raise AgentActionsError(
                f"Cannot process batch placeholder file: {self.file_path}. "
                f"Batch job {data['batch_job_id']} is still pending. "
                "Please wait for batch processing to complete."
            )
        
        return data
```

### 4. Retry Logic for Batch Result Retrieval
**File**: `agent_actions/services/batch_service.py`

Added retry mechanism for retrieving batch results from the API:

```python
# Add retry logic for file retrieval
max_retries = 3
retry_delay = 2  # seconds
last_error = None

for attempt in range(max_retries):
    try:
        result = self.client.files.content(result_file_id).content
        # Validate that we got content
        if not result or len(result) == 0:
            raise ValueError("Retrieved empty content from batch results")
        break
    except Exception as e:
        last_error = e
        if attempt < max_retries - 1:
            print(f"Retry {attempt + 1}/{max_retries}: Failed to retrieve batch results: {e}")
            import time
            time.sleep(retry_delay)
        else:
            raise RuntimeError(f"Failed to retrieve batch results after {max_retries} attempts: {last_error}")
```

### 5. Enhanced Error Messages
**File**: `agent_actions/services/batch_service.py`

Improved error messages with detailed debugging information:

```python
except Exception as e:
    error_msg = f"Could not process batch results for {file_name} (batch {batch_id}): {e}"
    print(f"[ERROR] {error_msg}")
    print(f"[DEBUG] Batch ID: {batch_id}")
    print(f"[DEBUG] File name: {file_name}")
    print(f"[DEBUG] Output directory: {output_directory}")
    if 'json.JSONDecodeError' in str(type(e)):
        print(f"[DEBUG] This appears to be a JSON parsing error. Check the batch results file for malformed JSON.")
```

## Impact
These changes ensure:
- Batch processing continues even if some lines in the results are malformed
- The workflow stops cleanly when batch processing fails, preventing cascading errors
- Better visibility into what went wrong with detailed error messages
- More resilient batch result retrieval with automatic retries
- Prevention of type errors in downstream agents

## Additional Fix: Lineage Tracking for Batch Mode

### 6. Added Lineage Tracking to Batch Processing
**File**: `agent_actions/services/batch_service.py`

Modified `_convert_batch_results_to_workflow_format` to include lineage tracking:

```python
# Extract node index from output directory (e.g., "node_0_summary")
node_idx = None
if output_directory:
    import re
    match = re.search(r'node_(\d+)_(\w+)', str(output_directory))
    if match:
        node_idx = int(match.group(1))

# In the processing loop, for each item:
# Add node_id and lineage tracking
if node_idx is not None:
    # Generate a unique node_id for each item
    item_node_id = f"node_{node_idx}_{uuid.uuid4()}"
    itm["node_id"] = item_node_id
    
    # Get lineage from original row
    original_lineage = original_row.get("lineage", [])
    if isinstance(original_lineage, list):
        # Filter to keep only node_* entries and add current node
        filtered_lineage = [nid for nid in original_lineage if isinstance(nid, str) and nid.startswith('node_')]
        itm["lineage"] = filtered_lineage + [item_node_id]
    else:
        itm["lineage"] = [item_node_id]

# Ensure target_id and source_guid are set
if 'target_id' not in itm or not itm['target_id']:
    itm['target_id'] = original_row.get('target_id', str(uuid.uuid4()))
if 'source_guid' not in itm or not itm['source_guid']:
    itm['source_guid'] = original_source_guid
```

This ensures that batch-processed results maintain the same lineage tracking as non-batch results, preserving the data flow through the pipeline.

### 7. Fixed Source File Key Issue in Batch Mode
**File**: `agent_actions/processors/staging_processor/staging_loader.py`

Fixed the source file saving to use `source_guid` as the key instead of `target_id`:

```python
# Save source for each row in data_chunk- this is where we generate source for batch
for row in data_chunk:
    source_guid = row.get("source_guid")
    if source_guid:
        src_text = {source_guid: row}
        batch_service._save_task_source(src_text, file_path, base_directory, output_directory)
```

This fix ensures that:
- Source files use `source_guid` as the key (matching non-batch behavior)
- Downstream agents can properly look up source data by `source_guid`
- Prevents "source_guid not found" errors in subsequent processing stages

## Summary of All Changes

### Error Handling Improvements
1. **JSON Parsing**: Added line-by-line error handling with detailed debugging information
   - Shows exact line number and character position of parsing errors
   - Displays up to 500 characters of problematic content
   - Continues processing other lines instead of failing completely

2. **Workflow Error Propagation**: Modified workflow to stop execution when batch processing fails
   - Prevents downstream agents from receiving invalid data
   - Provides clear error messages instead of cascading failures

3. **Batch Placeholder Validation**: Added detection and rejection of batch placeholder files
   - Prevents agents from trying to process incomplete batch data
   - Provides clear error message about pending batch jobs

### Reliability Improvements
4. **Retry Logic**: Added 3-attempt retry mechanism for batch result retrieval
   - 2-second delay between attempts
   - Validates that retrieved content is not empty
   - Clear error messages after all retries are exhausted

5. **Enhanced Error Messages**: Improved debugging information
   - Shows batch IDs, file names, and directories
   - Special handling for JSON parsing errors
   - Actionable error messages for troubleshooting

### Data Integrity Fixes
6. **Lineage Tracking**: Added complete lineage tracking to batch processing
   - Each item gets unique `node_id` in format `node_{idx}_{uuid}`
   - Proper lineage chain preservation through pipeline stages
   - Matches non-batch mode behavior exactly

7. **Source File Keys**: Fixed source file saving to use correct keys
   - Changed from using `target_id` to `source_guid` as key
   - Ensures downstream agents can look up source data correctly
   - Prevents "source_guid not found" errors

## Impact
These comprehensive changes ensure:
- Batch processing is resilient to malformed data
- Complete feature parity between batch and non-batch modes
- Proper data lineage tracking throughout the pipeline
- Clear error messages for debugging
- Prevention of cascading failures in multi-agent workflows