# Parallel Execution with Execution Levels

## Overview

Agent-actions now supports **automatic parallel execution** of agents within the same dependency level. This feature provides significant performance improvements (2-5× speedup) for workflows with parallelizable agents, without requiring any configuration changes.

## How It Works

### Execution Levels

The workflow engine automatically computes **execution levels** from your dependency graph:

```
extract → [gen_1, gen_2, gen_3] → validate → [enrich_1, enrich_2, enrich_3]

Levels:
  Level 0: [extract]                  (sequential)
  Level 1: [gen_1, gen_2, gen_3]      (parallel - 3 agents)
  Level 2: [validate]                 (sequential)
  Level 3: [enrich_1, enrich_2, enrich_3]  (parallel - 3 agents)
```

**Key Properties:**
- Agents in the **same level** can run in **parallel**
- Level **N+1** waits for **all agents** in level **N** to complete
- Dependencies are **always respected**

### Auto-Detection

The system automatically detects when parallel execution will benefit your workflow:

```python
# Purely sequential workflow (A → B → C → D)
Levels: [[A], [B], [C], [D]]
→ Uses sequential execution (no benefit from parallel)

# Workflow with parallelism (A → [B, C, D] → E)
Levels: [[A], [B, C, D], [E]]
→ Uses parallel execution (3 agents run concurrently in level 1)
```

## Usage

### Automatic (Recommended)

No configuration needed! Just run your workflow:

```bash
agent-actions run -a my_workflow
```

Output:
```
Starting workflow execution...
🔀 Using parallel execution (auto-detected)...
📊 Execution: 4 level(s)
  Level 0: extract (sequential)
  Level 1: 3 agents in parallel - gen_1, gen_2, gen_3
  Level 2: validate (sequential)
  Level 3: 3 agents in parallel - enrich_1, enrich_2, enrich_3

Level 0: Starting 1 agent(s)...
  ✓ extract (30.2s)
Level 0 complete (30.2s)

Level 1: Starting 3 agents in parallel...
  ✓ gen_1 (30.1s)
  ✓ gen_2 (30.0s)
  ✓ gen_3 (30.2s)
Level 1 complete (30.2s)

Level 2: Starting 1 agent(s)...
  ✓ validate (30.1s)
Level 2 complete (30.1s)

Level 3: Starting 3 agents in parallel...
  ✓ enrich_1 (30.0s)
  ✓ enrich_2 (30.1s)
  ✓ enrich_3 (30.2s)
Level 3 complete (30.2s)

🎉 Workflow Complete
Total time: ~120s (vs 240s sequential) = 2× speedup
```

### Manual Control

#### Force Parallel Execution
```bash
agent-actions run -a my_workflow --parallel
```

#### Force Sequential Execution
```bash
agent-actions run -a my_workflow --no-parallel
```

Useful for:
- Debugging workflows
- Comparing performance
- Resource-constrained environments

## Performance

### Expected Speedup

The speedup depends on your workflow structure:

| Pattern | Sequential Time | Parallel Time | Speedup |
|---------|----------------|---------------|---------|
| **3 parallel agents** | 3 × 30s = 90s | 30s | **3×** |
| **Diamond (A → [B,C] → D)** | 4 × 30s = 120s | 3 × 30s = 90s | **1.3×** |
| **Multi-level (A → [B,C,D] → E → [F,G])** | 7 × 30s = 210s | 4 × 30s = 120s | **1.75×** |
| **Linear (A → B → C → D)** | 4 × 30s = 120s | 4 × 30s = 120s | **1× (no benefit)** |

### Concurrency Limit

By default, max **5 concurrent agents** per level to prevent resource exhaustion.

For 10 agents in same level:
- Without limit: All 10 run concurrently
- With limit=5: Run in 2 batches (5 + 5)

### Batch Mode Compatibility

**Batch agents work naturally with parallel execution:**

```yaml
# Level with 3 batch agents
agents:
  - batch_1: {run_mode: batch}
  - batch_2: {run_mode: batch}
  - batch_3: {run_mode: batch}
```

**Execution:**
```
Run 1:
  Level 0: [batch_1, batch_2, batch_3]
  → All 3 submit batch jobs in parallel (3s total)
  → Exit workflow

Run 2:
  Level 0: Check all 3 batch statuses in parallel
  → All complete
  → Continue to next level
```

## Common Patterns

### 1. Map-Reduce

```yaml
# Parallel map, sequential reduce
mapper → [process_1, process_2, process_3] → reducer

Levels:
  [mapper]
  [process_1, process_2, process_3]  # Parallel
  [reducer]

Speedup: 3× on map phase
```

### 2. Multi-Stage Pipeline

```yaml
# Multiple parallel stages
extract → [validate_1, validate_2] → transform → [enrich_1, enrich_2, enrich_3]

Levels:
  [extract]
  [validate_1, validate_2]        # Parallel
  [transform]
  [enrich_1, enrich_2, enrich_3]  # Parallel

Speedup: ~1.8×
```

### 3. Parallel Loop Agents

```yaml
# Loop with mode='parallel' (default)
actions:
  - name: generate_distractors
    loop:
      param: variant
      range: [1, 3]
      mode: parallel

Expands to:
  generate_distractors_1 ─┐
  generate_distractors_2 ─┼→ [all in same level, run in parallel]
  generate_distractors_3 ─┘
```

### 4. Mixed Sequential and Parallel Loops

```yaml
# Sequential loop followed by parallel loop
actions:
  - name: refine
    loop:
      param: stage
      range: [1, 3]
      mode: sequential  # Chain: 1 → 2 → 3

  - name: validate
    loop:
      param: validator
      range: [1, 3]
      mode: parallel  # All 3 in parallel
    dependencies: [refine]

Levels:
  [refiner_1]
  [refiner_2]
  [refiner_3]
  [validate_1, validate_2, validate_3]  # Parallel
```

## Edge Cases Handled

### 1. Intermediate Dependencies

**THE edge case that motivated this design:**

```yaml
[parallel_group_1] → intermediate_agent → [parallel_group_2]

# Naive approach: Would run all in parallel (WRONG!)
# Level-based: Respects dependencies (CORRECT!)

Levels:
  [parallel_group_1]       # Parallel
  [intermediate_agent]     # Waits for all group 1
  [parallel_group_2]       # Parallel
```

### 2. Partial Parallelism

```yaml
# Some agents independent, some dependent
A (independent) → B
C (independent) → D

Levels:
  [A, C]  # Both independent, run in parallel
  [B, D]  # Both depend on level 0, run in parallel
```

### 3. Error Handling

Error in level N **stops all subsequent levels**:

```
Level 0: A ✓
Level 1: [B ✓, C ✗, D ✓]  # C fails
→ Error detected, stop workflow
Level 2: E  # Never executes
```

## Troubleshooting

### "Using sequential execution" (when expecting parallel)

**Cause:** All levels have only 1 agent (purely sequential workflow)

**Check:**
```bash
# Review dependencies
agent-actions run -a my_workflow

# Look for: "Level N: agent_name (sequential)"
```

### Slower than expected

**Causes:**
1. **Concurrency limit too low** - Default is 5, increase if needed
2. **Sequential dependencies** - Review workflow structure
3. **Batch mode agents** - Batch submission is fast but jobs run async

### Parallel execution not detected

**Cause:** Agents have different dependencies

```yaml
# This won't parallelize:
agent_1: {dependencies: [A]}
agent_2: {dependencies: [B]}

# Different dependencies → different levels
```

**Fix:** Ensure agents share same dependencies:
```yaml
agent_1: {dependencies: [A]}
agent_2: {dependencies: [A]}  # Same dependency → same level
```

## Implementation Details

### Algorithm: BFS-Based Level Assignment

```python
def _compute_execution_levels():
    levels = []
    assigned = set()

    while unassigned_agents_remain:
        # Find agents whose dependencies are all satisfied
        current_level = [
            agent for agent in execution_order
            if all(dep in assigned for dep in agent.dependencies)
        ]

        levels.append(current_level)
        assigned.update(current_level)

    return levels
```

**Complexity:** O(V + E) where V = agents, E = dependencies

### Execution: Level-by-Level with asyncio

```python
async def async_run():
    levels = _compute_execution_levels()

    for level in levels:
        if len(level) == 1:
            # Single agent - run directly
            await run_agent(level[0])
        else:
            # Multiple agents - run in parallel
            tasks = [run_agent(agent) for agent in level]
            await asyncio.gather(*tasks)  # Fail-fast
```

## Performance Metrics

The system tracks:
- **Execution time per level**
- **Number of parallel agents per level**
- **Total workflow time**
- **Achieved speedup vs sequential**

Example output:
```
📊 Performance Summary:
  Total agents: 8
  Execution levels: 4
  Parallel levels: 2 (levels 1, 3)

  Level 0: 30.2s (1 agent)
  Level 1: 30.2s (3 agents in parallel)
  Level 2: 30.1s (1 agent)
  Level 3: 30.2s (3 agents in parallel)

  Total time: 120.7s
  Sequential time: 241.2s
  Speedup: 2.0×
```

## Best Practices

1. **Let auto-detection work** - No config needed
2. **Design for parallelism** - Use same dependencies where possible
3. **Monitor speedup** - Check actual performance gains
4. **Use --no-parallel for debugging** - Easier to trace issues
5. **Batch mode:** Design workflows where batch agents are in same level

## Migration from Sequential

**No changes required!** Existing workflows automatically benefit:

```yaml
# Before: All run sequentially
# After: Automatic parallelization where possible
# Config: No changes needed ✅
```

**To opt-out:**
```bash
agent-actions run -a my_workflow --no-parallel
```

## Future Enhancements

Planned features:
- **Dynamic concurrency** based on system resources
- **Priority scheduling** within levels
- **Distributed execution** across machines
- **Cost optimization** for batch/API-based agents
- **Visualization** of execution levels

## Breaking Changes

### previous_agent_type in Parallel Execution

**Behavior Change**: `previous_agent_type` is not updated for agents executing in parallel to avoid race conditions.

**Why**: When multiple agents run concurrently, there is no single "previous" agent - they all execute simultaneously. Updating this shared state causes non-deterministic behavior.

**Impact**:
- **Low** - Most workflows don't rely on this value
- In parallel execution, `previous_agent_type` represents the last **sequential** agent (or `None` if workflow starts with parallel agents)
- Sequential execution behavior is unchanged

**Mitigation**:
- Use `agent_idx` for ordering information
- Access dependencies directly from `agent_configs` if needed

**Example**:
```python
# Sequential execution (unchanged)
agent_1 → agent_2 → agent_3
# previous_agent_type always defined: agent_1, agent_2, agent_3

# Parallel execution (new behavior)
agent_1 → [agent_2, agent_3, agent_4] → agent_5
# Level 0: agent_1
#   previous_agent_type = agent_1
# Level 1: agent_2, agent_3, agent_4 (parallel)
#   previous_agent_type = agent_1 (not updated, no race condition)
# Level 2: agent_5
#   previous_agent_type = agent_1 (still not updated from parallel agents)
```

## Summary

**Level-based parallel execution:**
- ✅ **Automatic** - No configuration needed
- ✅ **Safe** - Dependencies always respected
- ✅ **Fast** - 2-5× speedup for parallel workflows
- ✅ **Batch compatible** - Works with batch mode
- ⚠️ **Breaking change** - `previous_agent_type` behavior modified for parallel agents (low impact)

**Just run your workflow - parallelism happens automatically!** 🚀
