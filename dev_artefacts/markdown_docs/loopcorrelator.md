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

### Loop Modes: Parallel and Sequential

The Loop Output Correlator is **mode-agnostic** and works identically for both parallel and sequential loop execution modes.

#### Parallel Loops (Default)

In parallel mode, all loop iterations execute concurrently:

```yaml
actions:
  - name: generate_variants
    loop:
      param: variant_id
      range: [1, 3]
      mode: parallel  # All run concurrently

    prompt: "Generate variant ${variant_id}"
```

**Execution Timeline:**
```
t=0s:  variant_1, variant_2, variant_3 start simultaneously
t=30s: All variants complete (assuming 30s per iteration)
t=30s: Correlator merges outputs
t=30s: Downstream agent receives correlated data
```

**Dependency Structure:**
- `variant_1` depends on parent agent
- `variant_2` depends on parent agent
- `variant_3` depends on parent agent
- All execute in parallel when parent completes

#### Sequential Loops

In sequential mode, iterations execute in order with each iteration depending on the previous:

```yaml
actions:
  - name: refine_data
    loop:
      param: stage
      range: [1, 3]
      mode: sequential  # Iterations run in order

    prompt: "Refine stage ${stage}: improve output from stage ${stage-1}"
    observe:
      - refined_output_${stage}
```

**Execution Timeline:**
```
t=0s:   stage_1 starts
t=30s:  stage_1 completes, stage_2 starts
t=60s:  stage_2 completes, stage_3 starts
t=90s:  stage_3 completes
t=90s:  Correlator merges outputs
t=90s:  Downstream agent receives correlated data
```

**Dependency Structure:**
- `refine_data_1` depends on parent agent
- `refine_data_2` depends on `refine_data_1`
- `refine_data_3` depends on `refine_data_2`
- Iterations execute sequentially

#### Why the Correlator is Mode-Agnostic

The Loop Output Correlator operates **after** all loop iterations complete, regardless of execution mode:

1. **Barrier Point**: The correlator acts as a barrier - it only runs when all loop iterations are complete
2. **Output Collection**: It scans output directories from all iterations, whether they ran in parallel or sequentially
3. **Correlation Logic**: Correlation by `source_guid` or `loop_correlation_id` is independent of execution order
4. **Data Merging**: The merging process is the same - group records by identifier, merge fields from all iterations

**Example with Sequential Loop:**

```yaml
actions:
  - name: extract_data
    prompt: "Extract data from input"

  - name: enhance
    loop:
      param: pass
      range: [1, 3]
      mode: sequential
    prompt: "Enhancement pass ${pass}"
    observe:
      - enhanced_data_${pass}

  - name: aggregate
    loop_consumption:
      source: enhance
      pattern: merge
    prompt: "Aggregate all enhancements"

plan:
  - extract_data
  - enhance <- extract_data
  - aggregate <- enhance
```

**Execution Flow:**
1. `extract_data` runs
2. `enhance_1` runs (depends on `extract_data`)
3. `enhance_2` runs (depends on `enhance_1`)
4. `enhance_3` runs (depends on `enhance_2`)
5. **Correlator detects**: `aggregate` depends on loop base name `enhance`
6. **Correlator collects**: Outputs from `enhance_1`, `enhance_2`, `enhance_3`
7. **Correlator merges**: Records with same `source_guid` are combined
8. **Correlator writes**: Correlated data to `aggregate` input directory
9. `aggregate` runs with merged data

**Output Structure:**

Each iteration produces records:
```json
// enhance_1 output
{"source_guid": "record_A", "enhanced_data_1": "...", ...}

// enhance_2 output
{"source_guid": "record_A", "enhanced_data_2": "...", ...}

// enhance_3 output
{"source_guid": "record_A", "enhanced_data_3": "...", ...}
```

Correlator merges into:
```json
{
  "source_guid": "record_A",
  "enhanced_data_1": "...",
  "enhanced_data_2": "...",
  "enhanced_data_3": "...",
  ...
}
```

#### Performance Characteristics

**Parallel Loop Correlation:**
- **Iteration Time**: All iterations run concurrently (~30s for 3 iterations)
- **Correlation Time**: Same (scans 3 output directories)
- **Total Time**: ~30s + correlation overhead

**Sequential Loop Correlation:**
- **Iteration Time**: Iterations run in order (~90s for 3 iterations × 30s each)
- **Correlation Time**: Same (scans 3 output directories)
- **Total Time**: ~90s + correlation overhead

**Key Insight**: The correlation process is identical; only the iteration execution differs.

#### Batch Mode Compatibility

The correlator also works identically in batch mode for both loop types:

**Parallel Batch Loop:**
```yaml
actions:
  - name: process_items
    loop: {param: i, range: [1, 3], mode: parallel}
    run_mode: batch
```
- All 3 batch jobs submitted together
- All complete asynchronously
- Correlator merges results when all complete

**Sequential Batch Loop:**
```yaml
actions:
  - name: refine_items
    loop: {param: stage, range: [1, 3], mode: sequential}
    run_mode: batch
```
- Batch job 1 submitted → completes
- Batch job 2 submitted → completes
- Batch job 3 submitted → completes
- Correlator merges results when all complete

In both cases, the correlation logic is identical - the correlator simply waits for all iterations to complete before merging outputs.

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

## Breaking Changes (v3.0) - Explicit Loop Consumption

### New Pattern Required

As of v3.0, the Loop Output Correlator requires **explicit consumption declarations**. The previous automatic dependency detection has been removed to provide better control and clarity.

#### New Required Configuration

Consumers must now explicitly declare loop consumption:

```yaml
- name: reconstruct_options
  kind: tool
  impl: qanalabs-quiz-gen.test2.apply_edited_distractors
  loop_consumption:
    source: "generate_distractors"
    pattern: "merge"
```

#### What Changed

**Before (Automatic Detection):**
```yaml
plan:
  - generate_distractors <- generate_scenarios
  - reconstruct_options <- generate_distractors  # Auto-detected loop dependency
```

**After (Explicit Declaration):**
```yaml
plan:
  - generate_distractors <- generate_scenarios
  - reconstruct_options  # No automatic dependency expansion

actions:
  - name: reconstruct_options
    loop_consumption:      # REQUIRED for loop consumption
      source: "generate_distractors"
      pattern: "merge"
```

### Merge Pattern

The system supports the `"merge"` pattern:

#### `"merge"` (Default)
Dictionary update behavior - later values overwrite earlier ones:
```json
{
  "distractor_1": "Wrong answer A",
  "distractor_2": "Wrong answer B",
  "distractor_3": "Wrong answer C"
}
```

### Important Behavioral Change

**Without `loop_consumption` configuration**, agents now receive **standard sequential input** (output from immediately preceding agent), not merged loop outputs.

**Example:**
For execution order: `['loop_1', 'loop_2', 'loop_3', 'consumer']`

- **Without loop_consumption**: `consumer` gets input from `node_2_loop_3` (only last loop's output)
- **With loop_consumption**: `consumer` gets merged input from all loop agents

### Loop Correlation IDs

The system now automatically generates unique `loop_correlation_id` values for robust record correlation:

#### Automatic Generation
- When records enter loop correlation without a `loop_correlation_id`, the system automatically generates one
- Each unique `source_guid` gets a consistent `loop_correlation_id` across all loop iterations
- This provides more reliable correlation than relying solely on `source_guid`

#### Example Flow
```json
// Input to loop (no correlation ID yet)
{"source_guid": "record-1", "content": {"question": "What is 2+2?"}}

// After loop correlation processing
{"source_guid": "record-1", "loop_correlation_id": "abc-123-def", "content": {...}}

// All loop iterations for this record will share the same loop_correlation_id
```

#### Benefits
- **Reliability**: Works even if `source_guid` changes during processing
- **Consistency**: Same record gets same correlation ID across all loops
- **Debugging**: Easy to trace record flow through loop iterations
- **Partial Failures**: Records missing from some loops are still properly correlated

### Migration Required

All workflows using loop dependencies must add explicit `loop_consumption` configuration to consuming agents. There is no automatic migration or backward compatibility.

## Position-Based Loop Correlation IDs (v4.0)

### The Problem Solved

Previously, when multiple records shared the same `source_guid` (e.g., multiple questions from the same source), they would be incorrectly merged into a single record during loop correlation. This happened because the correlator used `source_guid` as the grouping key.

### Solution: Position-Based Correlation IDs

The system now generates unique `loop_correlation_id` values based on the **position** of each record in the input list, ensuring each record maintains its identity across loop iterations.

#### How It Works

1. **Record Processing**: When loop agents process input data, each record gets a position-based `loop_correlation_id`
   ```python
   # Record 0 gets: loop_correlation_id = "generate_distractors:position_0:"
   # Record 1 gets: loop_correlation_id = "generate_distractors:position_1:"
   # Record 2 gets: loop_correlation_id = "generate_distractors:position_2:"
   # Record 3 gets: loop_correlation_id = "generate_distractors:position_3:"
   ```

2. **Consistent Across Loops**: The same position gets the same correlation ID in all loop iterations
   ```python
   # All loop iterations (1, 2, 3) assign the same correlation ID to position 0
   ProcessorUtils.get_or_create_position_based_loop_correlation_id(0, "generate_distractors")
   ```

3. **Correlation**: Records are grouped by `loop_correlation_id` instead of `source_guid`
   ```python
   # Groups records by their position-based correlation ID
   correlation_key = record_copy.get('loop_correlation_id')
   correlation_groups[correlation_key][loop_agent] = record_copy
   ```

#### Example Flow

**Input** (4 questions, same source_guid):
```json
[
  {"source_guid": "same-guid", "content": {"question": "Question 1"}},
  {"source_guid": "same-guid", "content": {"question": "Question 2"}},
  {"source_guid": "same-guid", "content": {"question": "Question 3"}},
  {"source_guid": "same-guid", "content": {"question": "Question 4"}}
]
```

**After Position-Based Processing**:
```json
[
  {"source_guid": "same-guid", "loop_correlation_id": "abc-123", "content": {"question": "Question 1"}},
  {"source_guid": "same-guid", "loop_correlation_id": "def-456", "content": {"question": "Question 2"}},
  {"source_guid": "same-guid", "loop_correlation_id": "ghi-789", "content": {"question": "Question 3"}},
  {"source_guid": "same-guid", "loop_correlation_id": "jkl-012", "content": {"question": "Question 4"}}
]
```

**Final Output** (all 4 questions preserved):
```json
[
  {"source_guid": "same-guid", "loop_correlation_id": "abc-123", "content": {"question": "Question 1", "distractor_1": "...", "distractor_2": "...", "distractor_3": "..."}},
  {"source_guid": "same-guid", "loop_correlation_id": "def-456", "content": {"question": "Question 2", "distractor_1": "...", "distractor_2": "...", "distractor_3": "..."}},
  {"source_guid": "same-guid", "loop_correlation_id": "ghi-789", "content": {"question": "Question 3", "distractor_1": "...", "distractor_2": "...", "distractor_3": "..."}},
  {"source_guid": "same-guid", "loop_correlation_id": "jkl-012", "content": {"question": "Question 4", "distractor_1": "...", "distractor_2": "...", "distractor_3": "..."}}
]
```

### Implementation Details

#### ProcessorUtils Methods
```python
# Generate position-based correlation ID
ProcessorUtils.get_or_create_position_based_loop_correlation_id(
    record_index=0,
    loop_base_name="generate_distractors"
)

# Add correlation ID to record during processing
ProcessorUtils.add_loop_correlation_id(
    obj,
    agent_config,
    record_index=0  # Position-based when provided
)
```

#### Loop Correlator Requirements
- Records entering loop correlation **MUST** have `loop_correlation_id`
- No fallback to `source_guid` - correlation fails if ID is missing
- Correlation groups by `loop_correlation_id` exclusively

#### Error Handling
```python
# Strict validation in loop correlator
correlation_key = record_copy.get('loop_correlation_id')
if not correlation_key:
    raise ValueError(f"Loop record missing required loop_correlation_id")
```

### Benefits

- **Preserves Record Identity**: Multiple records with same source_guid stay separate
- **Consistent Correlation**: Same position correlates across all loop iterations
- **Predictable Behavior**: Position-based IDs are deterministic and debuggable
- **Backwards Compatible**: Falls back to source_guid-based IDs for non-loop contexts

## GitHub Issues Resolved

### Issue #385: "Fix loop merge data loss: 5 records become 1 due to non-unique correlation key"

**Problem Solved**: The position-based loop correlation ID system (v4.0) directly addresses this critical data loss issue.

**Root Cause**: The original issue occurred because multiple records shared the same `source_guid`, causing the loop correlator to merge them into a single record during correlation.

**Our Solution**: Position-based correlation IDs ensure each record gets a unique identifier based on its position in the input list, shared consistently across all loop iterations:

```python
# Before (data loss):
correlation_key = record_copy.get('source_guid')  # Same for multiple records

# After (preserves all records):
correlation_key = record_copy.get('loop_correlation_id')  # Unique per position
```

**Impact**:
- ✅ Preserves all records during loop correlation
- ✅ Maintains record identity across loop iterations
- ✅ Works correctly even when multiple records have identical source_guid
- ✅ No data loss in parallel loop workflows

### Related Issues Potentially Addressed

The position-based correlation system also provides foundation for several other loop consumption patterns:

- **Issue #386**: "Add aggregate consumption pattern" - Reliable correlation enables proper aggregation
- **Issue #387**: "Add select consumption pattern" - Correct correlation ensures all records are available for selection
- **Issue #388**: "Add independent consumption pattern" - Position-based IDs support independent tracking
- **Issue #390**: "Add reduction consumption pattern" - Proper correlation enables complex reduction logic

## Future Enhancements

- Support for nested loops
- Performance optimizations for large datasets
- Cross-workflow correlation capabilities
- Field conflict resolution strategies
- Correlation statistics and reporting