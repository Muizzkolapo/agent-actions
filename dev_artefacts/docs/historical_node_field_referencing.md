# Historical Node Field Referencing

## Overview

This feature enables referencing outputs from upstream agents in your workflow using `{action_name.field}` syntax, similar to how `{source.field}` works. This allows you to access historical node data from any previous step in your pipeline using lineage tracking.

## Feature Description

**What it does:** Allows you to reference any field from any upstream agent's output in your prompts.

**How it works:** Uses lineage tracking and source_guid to locate and load the exact record from historical target files.

**Why it's useful:** Enables complex multi-stage reasoning where later agents can access outputs from any earlier agent, not just immediate predecessors.

## Syntax

```yaml
prompt: |
  Use data from upstream agents:
  {action_name.field}
```

### Supported References

- `{source.field}` - Data from staging/source (existing feature)
- `{action_name.field}` - Data from target/node_X_action_name (NEW)
- `{loop.field}` - Loop context data (existing feature)
- `{workflow.field}` - Workflow metadata (existing feature)

## Example Usage

### Basic Example

```yaml
agents:
  - name: fact_extractor
    agent_type: extract_facts
    prompt: Extract facts from: {source.page_content}
    output:
      - candidate_facts_list

  - name: flatten_the_facts
    agent_type: flatten
    dependencies: [fact_extractor]
    prompt: Flatten the facts
    output:
      - fact
      - quote
      - technical_level

  - name: cluster_list
    agent_type: cluster
    dependencies: [fact_extractor, flatten_the_facts]
    prompt: |
      Create clusters from these facts:

      Current fact: {flatten_the_facts.fact}
      Quote: {flatten_the_facts.quote}

      Original extracted facts: {fact_extractor.candidate_facts_list}

      Source document: {source.page_content}
    output:
      - cluster_id
      - cluster_name
```

### Advanced Example - Multi-Level References

```yaml
agents:
  - name: extract_entities
    prompt: Extract entities from: {source.text}
    output: [entities]

  - name: classify_entities
    dependencies: [extract_entities]
    prompt: Classify these entities: {extract_entities.entities}
    output: [classifications]

  - name: build_relationships
    dependencies: [extract_entities, classify_entities]
    prompt: |
      Build relationships between:
      Entities: {extract_entities.entities}
      Classifications: {classify_entities.classifications}
      Original text: {source.text}
    output: [relationships]

  - name: generate_graph
    dependencies: [extract_entities, classify_entities, build_relationships]
    prompt: |
      Generate knowledge graph from:
      - Entities: {extract_entities.entities}
      - Classifications: {classify_entities.classifications}
      - Relationships: {build_relationships.relationships}
```

## How It Works

### 1. Directory Structure

```
agent_io/
├── staging/
│   └── source/                      # {source.field}
│       └── file.json
└── target/
    ├── node_0_fact_extractor/       # {fact_extractor.field}
    │   └── file.json
    ├── node_1_flatten_the_facts/    # {flatten_the_facts.field}
    │   └── file.json
    └── node_2_cluster_list/         # Current processing
        └── file.json
```

### 2. Lineage Tracking

Each record contains:
```json
{
  "source_guid": "b4d28c32-9b2e-599a-b326-0e1beadbf751",
  "node_id": "node_1_77494d50-82ba-4626-bb0e-762a801fd3bc",
  "lineage": [
    "node_0_0f974859-6081-4640-92ba-09aa468eb6b9",
    "node_1_77494d50-82ba-4626-bb0e-762a801fd3bc"
  ],
  "content": { ... }
}
```

### 3. Resolution Process

When processing `{fact_extractor.candidate_facts_list}`:

1. **Find Node ID**: Search current record's lineage for `node_0_*` (fact_extractor is at index 0)
   - Found: `node_0_0f974859-6081-4640-92ba-09aa468eb6b9`

2. **Construct Path**: Build path to historical file
   - Path: `target/node_0_fact_extractor/file.json`

3. **Load Record**: Find record matching both:
   - `source_guid`: `b4d28c32-9b2e-599a-b326-0e1beadbf751`
   - `node_id`: `node_0_0f974859-6081-4640-92ba-09aa468eb6b9`

4. **Extract Field**: Return `content.candidate_facts_list`

5. **Replace in Prompt**: Replace `{fact_extractor.candidate_facts_list}` with actual value

## Benefits

✓ **Access Any Upstream Data**: Reference outputs from any previous agent
✓ **Maintains Data Lineage**: Uses existing lineage tracking for correctness
✓ **No Data Duplication**: Loads from existing target files
✓ **Backward Compatible**: Existing `{source.field}` continues to work
✓ **Type-Safe**: Uses the same field resolution as existing system
✓ **Graceful Degradation**: Missing data doesn't break processing

## Configuration Requirements

### ✅ No Manual Configuration Needed!

The system **automatically** makes ALL previous actions in the workflow available for referencing. You don't need to declare `dependencies` - just use `{action_name.field}` and it works!

```yaml
agents:
  - name: my_agent
    # No dependencies needed!
    prompt: Use {upstream_agent_1.field}  # ✓ Automatically available
```

### How It Works

The system automatically:
1. Reads the current record's `lineage`
2. Identifies ALL previous actions from lineage
3. Loads historical data for each action
4. Makes them all available in field_context

Agent indices are built automatically from your workflow configuration:

```yaml
agents:
  - name: fact_extractor     # idx: 0 - Auto-available to all later agents
  - name: flatten_facts      # idx: 1 - Auto-available to all later agents
  - name: cluster_list       # idx: 2 - Can reference fact_extractor & flatten_facts
```

## Technical Details

### New Components

1. **HistoricalNodeDataLoader** (`agent_actions/preprocessing/historical_node_loader.py`)
   - Loads historical node data from target files
   - Uses lineage + source_guid for precise record matching

2. **NodeMappingService** (`agent_actions/orchestration/node_mapper.py`)
   - Maps agent names to node indices
   - Provides node prefix and directory name utilities

3. **Enhanced DataGenerator**
   - Accepts `agent_indices` and `current_item` parameters
   - Loads historical data when building field context

### Integration Points

- **ApplicationContainer**: Builds agent_indices mapping
- **TargetContentProcessor**: Passes lineage and file_path to generator
- **DataGenerator**: Loads and merges historical data into field_context
- **PromptUtils**: Resolves field references (unchanged - works with new namespaces)

## Error Handling

The system gracefully handles:
- Missing historical files (returns None, continues processing)
- Invalid lineage data (skips historical loading)
- Missing fields (raises clear error during prompt resolution)
- File read errors (logs warning, continues without historical data)

## Performance Considerations

- **File I/O**: Each historical reference requires reading a JSON file
- **Caching**: No caching currently implemented (future optimization)
- **Recommendation**: Use historical references judiciously for agents that truly need cross-stage context

## Migration Guide

### Existing Workflows

No changes required! This feature is backward compatible and **automatically enabled**.

### New Workflows

Just use `{action_name.field}` syntax - no configuration needed:

```yaml
# Simple - works automatically!
agents:
  - name: agent_a
    output: [field_x]
  - name: agent_b
    output: [field_y]
  - name: agent_c
    # No dependencies needed - all previous actions auto-available!
    prompt: |
      From A: {agent_a.field_x}
      From B: {agent_b.field_y}
      From source: {source.original_data}
```

### Optional: Declare dependencies for clarity

While not required, you can still declare `dependencies` for documentation purposes:

```yaml
agents:
  - name: agent_c
    dependencies: [agent_a, agent_b]  # Optional - for clarity only
    prompt: "Use {agent_a.field_x}"   # Works with or without dependencies
```

## Testing

Comprehensive test coverage includes:

- **Unit Tests**: HistoricalNodeDataLoader, NodeMappingService
- **Integration Tests**: Full prompt formatting with historical references
- **Edge Cases**: Missing data, invalid lineage, file errors

Run tests:
```bash
pytest tests/preprocessing/test_historical_node_loader.py
pytest tests/orchestration/test_node_mapper.py
pytest tests/integration/test_historical_node_field_referencing.py
```

## Future Enhancements

Potential improvements:
- Caching loaded historical data within a file processing session
- Support for array indexing: `{agent.field[0].subfield}`
- Support for conditional loading: `{agent.field ?? default_value}`
- Performance metrics and optimization

## Examples from Test Suite

See `tests/integration/test_historical_node_field_referencing.py` for complete working examples.
