# Loop Output Correlator

The Loop Output Correlator is a core component of the agent-actions framework that enables parallel map-reduce patterns for workflow loops. It handles correlation of loop iteration outputs for downstream agents without breaking existing sequential execution patterns.

## Overview

When agents are configured with loops (e.g., `generate_distractors` with `range: [1, 3]`), the framework creates multiple parallel instances that execute independently. The Loop Output Correlator ensures that downstream agents can access all loop outputs in a correlated manner.

## Architecture

### Map-Reduce Pattern

The system implements a parallel map-reduce pattern:

1. **MAP Phase**: Loop iterations run in parallel
   - `generate_distractors_1` processes all records
   - `generate_distractors_2` processes all records
   - `generate_distractors_3` processes all records

2. **BARRIER**: Framework waits for all iterations to complete

3. **REDUCE Phase**: Outputs are correlated by source record
   - Records with the same `source_guid` are grouped together
   - Content from all loop iterations is merged into single records

4. **CONSUMPTION**: Downstream agents receive correlated data

### Data Flow

```
Source Data → Loop Agent 1 (distractor_1) ↘
            → Loop Agent 2 (distractor_2) → Correlator → Downstream Agent
            → Loop Agent 3 (distractor_3) ↗
```

## Implementation

### Key Components

#### LoopOutputCorrelator Class

Located in `agent_actions/core/graph/loop_correlator.py`:

```python
class LoopOutputCorrelator:
    """Correlates outputs from parallel loop executions for downstream consumption."""

    def detect_loop_dependencies(self, execution_order: List[str], agent_configs: Dict[str, Any])
    def prepare_correlated_input(self, agent_name: str, loop_sources: List[str], current_idx: int)
    def _load_agent_outputs_with_filenames(self, output_dir: Path) -> Tuple[List[Dict[str, Any]], set]
    def _correlate_by_source_record(self, loop_outputs: Dict[str, List[Dict[str, Any]]])
    def _write_correlated_data(self, output_dir: Path, correlated_data: List[Dict[str, Any]],
                              filename: str = "correlated_data.json")
```

#### Integration with AgentWorkflow

The correlator is integrated into the main workflow execution in `agent_workflow.py`:

```python
def _setup_correlation_if_needed(self, idx: int):
    """Setup correlation for agents that depend on loop outputs."""
    current_agent = self.execution_order[idx]
    loop_dependencies = self.loop_correlator.detect_loop_dependencies(
        self.execution_order, self.agent_configs
    )

    if current_agent in loop_dependencies:
        # Temporarily override setup_directories for correlation
        correlation_dir = self.loop_correlator.prepare_correlated_input(
            current_agent, loop_dependencies[current_agent], idx
        )
```

### Dependency Detection

The system automatically detects which agents depend on loop outputs:

1. **Loop Agent Identification**: Agents with naming pattern `{base_name}_{number}` (e.g., `generate_distractors_1`)
2. **Dependency Analysis**: Checks which non-loop agents depend on loop base names
3. **Correlation Mapping**: Creates mapping of dependent agents to their loop sources

Example:
```yaml
# This configuration creates a dependency
plan:
  - generate_distractors <- generate_scenarios  # Creates loop instances
  - reconstruct_options <- generate_distractors  # Depends on loop outputs
```

Results in correlation mapping:
```python
{
    "reconstruct_options": ["generate_distractors_1", "generate_distractors_2", "generate_distractors_3"]
}
```

### Data Correlation Process

#### 1. Output Collection

The correlator scans loop agent output directories and preserves original filenames:
```
agent_io/target/node_7_generate_distractors_1/Azure_AI_Questions.json
agent_io/target/node_8_generate_distractors_2/Azure_AI_Questions.json
agent_io/target/node_9_generate_distractors_3/Azure_AI_Questions.json
```

#### 2. Record Correlation

Records are correlated by `source_guid` with support for partial records:

**Input** (from 3 loop agents):
```json
// From generate_distractors_1
{
  "source_guid": "abc-123",
  "content": {"distractor_1": "First distractor", "why_incorrect_1": "Reason 1"}
}

// From generate_distractors_2
{
  "source_guid": "abc-123",
  "content": {"distractor_2": "Second distractor", "why_incorrect_2": "Reason 2"}
}

// From generate_distractors_3 (might be missing for some records)
{
  "source_guid": "abc-123",
  "content": {"distractor_3": "Third distractor", "why_incorrect_3": "Reason 3"}
}
```

**Output** (correlated):
```json
{
  "source_guid": "abc-123",
  "target_id": "...",
  "node_id": "...",
  "lineage": [...],
  "content": {
    "distractor_1": "First distractor",
    "why_incorrect_1": "Reason 1",
    "distractor_2": "Second distractor",
    "why_incorrect_2": "Reason 2",
    "distractor_3": "Third distractor",
    "why_incorrect_3": "Reason 3"
  }
}
```

**Partial Record Handling**: If a record exists in only some loop iterations (e.g., due to processing errors), it's still included with the available fields:
```json
{
  "source_guid": "def-456",
  "content": {
    "distractor_1": "Available distractor",
    "why_incorrect_1": "Available reason",
    "distractor_2": "Another available",
    "why_incorrect_2": "Another reason"
    // distractor_3 missing - loop 3 failed for this record
  }
}
```

#### 3. File System Integration

The correlator preserves original filenames and creates both target and source files:

**Target Data** (for processing):
```
agent_io/target/node_10_reconstruct_options/Azure_AI_Questions.json
```

**Source Data** (for source_data_loader):
```
agent_io/source/Azure_AI_Questions.json
```

This approach ensures:
- **Filename Preservation**: Original filenames are maintained throughout the pipeline
- **Compatibility**: Framework's `source_data_loader` can properly derive source paths
- **Multiple Files**: If loop agents produce multiple files, each is correlated separately

## Configuration

### Loop Configuration

Loops are configured in the agent YAML file:

```yaml
actions:
  - name: generate_distractors
    loop:
      param: stage
      range: [1, 3]
    schema:
      distractor_${stage}: string
      why_incorrect_${stage}: string
    writes:
      - distractor_${stage}
      - why_incorrect_${stage}
```

### Plan Dependencies

The plan section defines which agents depend on loop outputs:

```yaml
plan:
  - generate_distractors <- generate_scenarios
  - reconstruct_options <- generate_distractors  # This triggers correlation
```

## Use Cases

### Quiz Generation Example

In the qanalabs-quiz-gen workflow:

1. **Loop Execution**: `generate_distractors` creates 3 parallel instances
2. **Parallel Processing**: Each instance generates one distractor for all questions
3. **Correlation**: All distractors for each question are merged together
4. **Downstream Usage**: `reconstruct_options` receives complete distractor sets

### Benefits

- **Parallelization**: Loop iterations can run concurrently
- **Data Integrity**: Records remain correlated by source
- **Compatibility**: Works with existing sequential execution patterns
- **Flexibility**: Supports dynamic loop ranges and parameters

## Debugging

### Logging

The system provides debug output:
```
🔗 Using correlated input for reconstruct_options from 3 loop sources
```

### Verification

Check correlation results:
```bash
# Inspect correlation directory
ls agent_io/target/node_*_reconstruct_options/

# Verify correlation data (filename will match original)
cat agent_io/target/node_*_reconstruct_options/*.json

# Check source file creation (preserves original filename)
ls agent_io/source/*.json
```

### Common Issues

1. **Missing Loop Dependencies**: Ensure plan correctly specifies dependencies
2. **Source GUID Mismatches**: Verify all loop outputs use consistent `source_guid` values
3. **Filename Mismatches**: Ensure loop agents output files with consistent names
4. **Partial Records**: Records missing from some loops are now included with available fields

## Recent Improvements (v2.0)

### Filename Preservation
- Original filenames are now preserved instead of using generic `correlated_data.json`
- Each file from loop agents is processed and correlated separately
- Maintains consistency with the rest of the pipeline

### Robust Partial Record Handling
- Records no longer need to exist in ALL loop iterations
- If a record fails in one loop but succeeds in others, it's still included
- Useful for handling:
  - Processing errors in individual loops
  - Optional fields that some loops might skip
  - Gradual degradation instead of complete failure

### Example with Improvements

```python
# Before: Would lose record-2 entirely if loop 3 failed
# After: Includes record-2 with data from loops 1 and 2

# Loop 1 output: question_data.json
[{"source_guid": "record-1", "content": {"field_1": "value1"}},
 {"source_guid": "record-2", "content": {"field_1": "value1"}}]

# Loop 2 output: question_data.json
[{"source_guid": "record-1", "content": {"field_2": "value2"}},
 {"source_guid": "record-2", "content": {"field_2": "value2"}}]

# Loop 3 output: question_data.json (record-2 failed)
[{"source_guid": "record-1", "content": {"field_3": "value3"}}]

# Correlated output: question_data.json (preserves filename)
[{"source_guid": "record-1", "content": {"field_1": "value1", "field_2": "value2", "field_3": "value3"}},
 {"source_guid": "record-2", "content": {"field_1": "value1", "field_2": "value2"}}]  # Still included!
```

## Future Enhancements

- Support for nested loops
- Configurable correlation keys beyond `source_guid`
- Performance optimizations for large datasets
- Cross-workflow correlation capabilities
- Field conflict resolution strategies
- Correlation statistics and reporting