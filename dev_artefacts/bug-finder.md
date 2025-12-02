# Bug Finder: None-Safety Issues in Dictionary Operations

## Context
This prompt helps identify potential `NoneType` attribute/operation errors across the codebase, particularly in dictionary comprehensions, loops, and config handling.

## Bug Pattern Found
**Issue**: `'NoneType' object has no attribute 'get'` or `'NoneType' object has no attribute '<attr>'`

**Root Cause**: Code assumes dictionary values or objects are never None without defensive checks.

## Instructions for Claude Code

Please analyze the codebase and find all instances where we might encounter similar None-safety issues. Focus on these patterns:

### 1. Dictionary Comprehensions with Unsafe Operations
**Pattern**: `{k: v.get(...) for k, v in dict.items() if 'key' in v}`
**Problem**: If `v` is None, both `'key' in v` and `v.get()` will fail

**Search for**:
```python
# Dict comprehensions that access attributes/methods without None checks
{... for k, v in *.items() if ... in v}
{... v.get(...) for k, v in *.items() ...}
{... v[...] for k, v in *.items() ...}
{... v.attribute for k, v in *.items() ...}
```

**Example Fix**:
```python
# Before (unsafe)
agent_indices = {name: config.get('idx', 999)
                 for name, config in agent_configs.items()
                 if 'idx' in config}

# After (safe)
agent_indices = {name: config.get('idx', 999)
                 for name, config in agent_configs.items()
                 if config is not None and 'idx' in config}
```

### 2. For Loops with Unsafe Dictionary Value Access
**Pattern**: `for k, v in dict.items(): v['key']` or `v.get(...)`
**Problem**: If `v` is None, accessing it will fail

**Search for**:
```python
# Loops that access dictionary values without None checks
for ... in *.items():
    v.get(...)
    v['key']
    v.attribute
```

**Example Fix**:
```python
# Before (unsafe)
for agent_name, agent_config in self.agent_configs.items():
    agent_config['workflow_config_path'] = self.constructor_path

# After (safe)
for agent_name, agent_config in self.agent_configs.items():
    if agent_config is not None:
        agent_config['workflow_config_path'] = self.constructor_path
```

### 3. Chained .get() Calls Without None Checks
**Pattern**: `obj.get('key1').get('key2')`
**Problem**: If first .get() returns None, second call fails

**Search for**:
```python
# Chained get calls without intermediate None checks
*.get(...).get(...)
*.get(...)[...]
*.get(...).attribute
```

**Example Fix**:
```python
# Before (unsafe)
value = config.get('nested').get('value')

# After (safe)
nested = config.get('nested')
value = nested.get('value') if nested is not None else None
```

### 4. Function Parameters Passed as Dictionaries
**Pattern**: Functions receiving `dict` parameters that iterate over values
**Problem**: Dictionary might contain None values

**Search for**:
```python
# Functions that receive dicts and iterate without None safety
def func(configs: Dict[str, Dict]):
    for name, config in configs.items():
        # Operations on config without None check
```

### 5. Config/Registry Lookups
**Pattern**: `registry[key]` or `registry.get(key)` used without None checks
**Problem**: Lookup might return None

**Search for**:
```python
# Registry/config lookups that assume non-None
config = registry.get(...)
config['key']  # If config is None, this fails
config.get(...)  # If config is None, this fails
```

## Analysis Steps

1. **Search Phase**: Use Grep/Glob to find all occurrences of the patterns above
2. **Risk Assessment**: For each occurrence, determine:
   - Can the value ever be None?
   - Is there already a None check?
   - What would happen if it's None?
3. **Prioritization**: Focus on:
   - Dictionary comprehensions (high risk, hard to debug)
   - Config/agent_configs operations (high frequency)
   - Batch processing code (parallel execution amplifies issues)
4. **Reporting**: Create a list of findings with:
   - File and line number
   - Code snippet
   - Risk level (High/Medium/Low)
   - Suggested fix

## Specific Areas to Check

Based on the current bug, prioritize these files:
- `agent_actions/orchestration/target_generator.py` (lines 74, 134)
- `agent_actions/orchestration/agent_workflow.py` (line 170-174)
- `agent_actions/orchestration/node_mapper.py`
- `agent_actions/llm_invocation/batch/*.py`
- Any file that uses `agent_configs` or similar config dictionaries

## Output Format

For each finding, provide:
```
File: path/to/file.py:line_number
Risk: [High/Medium/Low]
Pattern: [Dict Comprehension / For Loop / Chained Get / etc.]

Code:
```python
# Current code snippet
```

Issue: Brief description of what could go wrong

Fix:
```python
# Suggested safe code
```
```

## Example Search Commands

```bash
# Find dict comprehensions with 'in' checks
grep -rn "for .* in .*\.items().*if .* in " agent_actions/

# Find .get() calls in comprehensions
grep -rn "\.get(.*) for .* in .*\.items()" agent_actions/

# Find chained .get() calls
grep -rn "\.get(.*)\.get(.*)" agent_actions/

# Find agent_configs usage
grep -rn "agent_configs\[" agent_actions/
grep -rn "agent_configs\.items()" agent_actions/
```

## Notes
- Focus on orchestration, batch, and config handling code
- Dict comprehensions are particularly risky because the error happens lazily
- Config dictionaries (agent_configs, dependency_configs, etc.) are common sources
- Recent changes to config handling may have exposed latent bugs
