# Feature: Agent Namespace Preservation for Input/Output Signature Control

## Issue Type
🚀 Feature Request / Architectural Enhancement

## Priority
🔴 **HIGH** - Blocks unified field referencing pattern (Issue #429)

## Summary
The pipeline currently passes **flat merged dictionaries** between agents, losing track of which agent produced which fields. This prevents the `{agent.field}` reference pattern from working, even though validation passes. We need **total control over agent namespaces, input signatures, and output signatures** to enable proper dependency field referencing.

## Problem Statement

### Current Behavior - Data Flows as Flat Dictionaries

When data flows through the pipeline from `agent_A → agent_B → agent_C`, all fields are merged into a single flat dictionary:

```python
# What actually flows between agents
{
  "source_guid": "...",
  "content": {
    "field_from_agent_A": "value1",
    "field_from_agent_B": "value2",
    "field_from_agent_C": "value3",
    "field_from_observe": "value4"
  }
}
```

**Problem:** There's no way to know which agent produced which field!

### Expected Behavior - Namespaced Agent Outputs

To support `{agent.field}` references, data should preserve agent namespaces:

```python
# What the {agent.field} pattern expects
{
  "source_guid": "...",
  "content": {
    "agent_A": {
      "field_from_agent_A": "value1"
    },
    "agent_B": {
      "field_from_agent_B": "value2"
    },
    "agent_C": {
      "field_from_agent_C": "value3"
    },
    "_observe": {
      "field_from_observe": "value4"
    }
  }
}
```

## User Impact

### Broken User Experience

**Workflow Configuration:**
```yaml
actions:
  - name: create_new_clusters
    kind: tool
    observe: [bloom_details, page_content]

  - name: fact_questionability
    dependencies: [create_new_clusters]
    prompt: "Based on {create_new_clusters.bloom_details}, evaluate..."
```

**What Happens:**
1. ✅ **Validation passes** - InputSignatureValidator sees `bloom_details` in `create_new_clusters` output
2. ❌ **Runtime fails** - `{create_new_clusters.bloom_details}` throws "Reference 'create_new_clusters' not found"

**Error Message:**
```
Problem: Reference 'create_new_clusters' not found.
Available: [bloom_details, page_content, ...]
```

**User Confusion:**
- "But `bloom_details` IS available! Why can't I reference it as `{create_new_clusters.bloom_details}`?"
- "Validation said it was valid, why does runtime fail?"
- "How do I know where `bloom_details` came from if multiple agents produce fields with the same name?"

### Affected Workflows

**All workflows using:**
- ✅ `{source.field}` - Works after Issue #436 fix
- ❌ `{agent.field}` - **Completely broken**
- ❌ `{agent.nested.field}` - **Completely broken**
- ✅ `{loop.iteration}` - Works (special case)
- ✅ `{workflow.metadata}` - Works (special case)

**Specifically blocks:**
- qanalabs-quiz-gen workflow
- Any workflow with multi-stage processing where later agents need to reference specific upstream agent outputs
- Workflows where multiple agents produce fields with the same name (ambiguity resolution)

## Root Cause Analysis

### Where Agent Namespace Is Lost

The pipeline merges outputs at multiple points without preserving provenance:

#### 1. **Agent Output Processing** (`target_data_generator.py`)

Agents produce outputs, but the output is immediately flattened:

```python
# Agent produces output
agent_output = {
  "new_field_1": "value1",
  "new_field_2": "value2"
}

# Output is merged with input WITHOUT preserving agent name
merged_data = {**input_data, **agent_output}  # ❌ Agent name lost!

# Should be:
merged_data = {
  **input_data,
  "agent_name": agent_output  # ✅ Preserve namespace
}
```

#### 2. **Observe/Side Collection Merging** (`data_processor.py`)

Fields from `observe` are merged alongside agent outputs:

```python
# Current: Everything flattened together
output = {
  "agent_field": "from agent",
  "observed_field": "from observe"  # ❌ No way to distinguish!
}

# Should be: Separate namespaces
output = {
  "agent_name": {
    "agent_field": "from agent"
  },
  "_observe": {
    "observed_field": "from observe"
  }
}
```

#### 3. **Dependency Data Passing** (`data_generator._format_prompt`)

When building `field_context` for prompt formatting:

```python
# Current (line 137)
field_context.update(contents)  # ❌ Flat merge

# Contents is:
# {'bloom_details': '...', 'page_content': '...'}

# Expects:
# {'create_new_clusters': {'bloom_details': '...', 'page_content': '...'}}
```

### Why Validation Passes But Runtime Fails

#### Validation Layer (Config Time) ✅
```python
# InputSignatureValidator checks agent configs
dep_config = {
  'output_schema': {'properties': {...}},
  'side_collection': ['bloom_details', 'page_content'],  # From observe
  'drops': []
}

# LLMContextUtils computes available fields
llm_context = compute_llm_context(dep_config)
# Returns: {'bloom_details', 'page_content', ...}

# Validator checks if 'bloom_details' is in llm_context
# ✅ YES - validation passes
```

#### Runtime Layer (Execution Time) ❌
```python
# PromptUtils.replace_field_references needs field_context
field_context = {
  'source': {...},
  'bloom_details': '...',  # ❌ Flat! No 'create_new_clusters' key
  'page_content': '...'
}

# Tries to resolve {create_new_clusters.bloom_details}
# Looks for field_context['create_new_clusters']['bloom_details']
# ❌ KeyError: 'create_new_clusters' not in field_context
```

**The Disconnect:** Validator checks "will the field exist?" but doesn't verify "will the agent namespace exist?"

## Technical Requirements

### 1. Agent Output Signature Preservation

**Requirement:** Track which agent produced which fields throughout the pipeline.

**Implementation Areas:**

#### A. Agent Output Wrapping
```python
# In target_data_generator.py or data_processor.py
def wrap_agent_output(agent_name: str, agent_output: Dict, observe_fields: Dict) -> Dict:
    """
    Wrap agent outputs to preserve namespace.

    Returns:
        {
            agent_name: {agent_output},
            '_observe': {observe_fields}
        }
    """
    return {
        agent_name: agent_output,
        '_observe': observe_fields if observe_fields else {}
    }
```

#### B. Dependency Output Structure
```python
# When passing to next agent
contents = {
    'extractor': {
        'summary': '...',
        'keywords': [...]
    },
    'classifier': {
        'category': 'tech',
        'confidence': 0.95
    },
    '_observe': {
        'id': '123',
        'url': 'https://...'
    }
}
```

### 2. Input Signature Declaration

**Requirement:** Allow agents to explicitly declare what inputs they expect.

**YAML Syntax:**
```yaml
actions:
  - name: fact_questionability
    dependencies: [create_new_clusters, validate_clusters]

    # NEW: Explicit input signature declaration
    inputs:
      from_create_new_clusters: [bloom_details, flagged_items]
      from_validate_clusters: [cluster_id, should_keep_cluster]
      from_observe: [page_content, url]

    # References in prompt now validated against input signature
    prompt: |
      Based on {create_new_clusters.bloom_details},
      evaluate cluster {validate_clusters.cluster_id}
      from content: {page_content}
```

**Benefits:**
- **Explicit contracts** - Clear what each agent expects
- **Better validation** - Catch missing dependencies at config load time
- **Self-documenting** - Easy to understand data flow
- **Ambiguity resolution** - When multiple agents produce same field name

### 3. Output Signature Enforcement

**Requirement:** Enforce that agents only expose fields declared in their output signature.

**YAML Syntax:**
```yaml
actions:
  - name: create_new_clusters
    kind: tool

    # NEW: Explicit output signature
    outputs:
      schema_fields: [cluster_id, should_keep_cluster, reasoning]
      observe_fields: [bloom_details, page_content]

    # System validates actual output matches declared signature
    schema: cluster_output
    observe: [bloom_details, page_content]
```

**Validation:**
```python
def validate_output_signature(agent_name: str,
                              declared_outputs: Dict,
                              actual_output: Dict) -> None:
    """Validate actual output matches declared signature."""

    declared_fields = set(declared_outputs.get('schema_fields', []))
    declared_observe = set(declared_outputs.get('observe_fields', []))

    actual_schema = set(actual_output.get(agent_name, {}).keys())
    actual_observe = set(actual_output.get('_observe', {}).keys())

    # Check for undeclared fields
    undeclared_schema = actual_schema - declared_fields
    if undeclared_schema:
        raise OutputSignatureError(
            f"Agent '{agent_name}' produced undeclared fields: {undeclared_schema}"
        )
```

### 4. Namespace-Aware Field Context Building

**Current Issue:**
```python
# data_generator.py:137
field_context.update(contents)  # ❌ Assumes contents is namespaced
```

**Required Fix:**
```python
def build_field_context(contents: Dict,
                       source_content: Any,
                       loop_context: Dict,
                       workflow_metadata: Dict) -> Dict:
    """
    Build field_context with proper namespace preservation.

    Args:
        contents: Namespaced dependency outputs:
                 {'agent1': {...}, 'agent2': {...}, '_observe': {...}}

    Returns:
        field_context ready for {agent.field} resolution
    """
    field_context = {}

    # Add source
    if source_content:
        field_context['source'] = source_content

    # Add dependency outputs (already namespaced)
    if isinstance(contents, dict):
        for agent_name, agent_data in contents.items():
            if agent_name != '_observe':  # Skip observe for now
                field_context[agent_name] = agent_data

        # Add observed fields at root level for backward compatibility
        if '_observe' in contents:
            field_context.update(contents['_observe'])

    # Add special contexts
    if loop_context:
        field_context['loop'] = loop_context
    if workflow_metadata:
        field_context['workflow'] = workflow_metadata

    return field_context
```

**Result:**
```python
field_context = {
    'source': {...},
    'create_new_clusters': {
        'cluster_id': '...',
        'bloom_details': '...'
    },
    'validate_clusters': {
        'should_keep_cluster': False
    },
    'bloom_details': '...',  # Backward compat: observe fields at root
    'page_content': '...',
    'loop': {...},
    'workflow': {...}
}
```

**Supports:**
- ✅ `{create_new_clusters.bloom_details}` - Namespaced access
- ✅ `{bloom_details}` - Backward compatible flat access
- ✅ `{source.field}` - Source access
- ✅ `{loop.iteration}` - Loop context

## Proposed Solution Architecture

### Phase 1: Data Structure Changes (Breaking Change)

#### 1.1 Update Agent Output Structure

**File:** `agent_actions/agents/processors/data_processor.py`

```python
def process_item(self, contents: Dict, generated_data: Any, source_guid: str, agent_name: str) -> List[Dict]:
    """
    Process a single item and wrap output with agent namespace.

    Args:
        agent_name: NEW - Name of the agent producing this output
    """
    # Process as before
    processed = self._process_generated_data(contents, generated_data, source_guid)

    # NEW: Wrap with agent namespace
    wrapped = []
    for item in processed:
        wrapped_item = self._wrap_with_namespace(
            agent_name=agent_name,
            agent_output=item,
            observe_fields=self._extract_observe_fields(contents, item)
        )
        wrapped.append(wrapped_item)

    return wrapped

def _wrap_with_namespace(self, agent_name: str, agent_output: Dict, observe_fields: Dict) -> Dict:
    """Wrap agent output to preserve namespace."""
    # Extract schema fields (agent's own output)
    schema_fields = {k: v for k, v in agent_output.items()
                     if k not in observe_fields}

    return {
        agent_name: schema_fields,
        '_observe': observe_fields,
        # Keep flat fields for backward compatibility (deprecate later)
        **agent_output
    }
```

#### 1.2 Update Field Context Building

**File:** `agent_actions/agents/generators/data_generator.py`

```python
def _format_prompt(self, contents: Dict, source_content: Optional[Any] = None, ...) -> Tuple[str, Dict]:
    """Format prompt with namespace-aware field context."""

    # Build namespace-aware field context
    field_context = self._build_field_context(contents, source_content, loop_context, workflow_metadata)

    # Replace field references with namespace support
    if field_context:
        source_loaded_prompt = PromptUtils.replace_field_references(
            source_loaded_prompt,
            field_context
        )

    return prompt, cleaned_contents

def _build_field_context(self, contents: Dict, source_content: Any,
                        loop_context: Dict, workflow_metadata: Dict) -> Dict:
    """
    Build field context with proper namespace preservation.

    Supports both:
    - New namespaced format: {'agent': {...}, '_observe': {...}}
    - Legacy flat format: {'field1': '...', 'field2': '...'}
    """
    field_context = {}

    if source_content:
        field_context['source'] = source_content

    if isinstance(contents, dict):
        # Check if contents is namespaced (has agent keys)
        has_namespaces = any(isinstance(v, dict) and k not in ['_observe', 'source', 'loop', 'workflow']
                            for k, v in contents.items())

        if has_namespaces:
            # NEW: Namespaced format
            for key, value in contents.items():
                if key == '_observe':
                    # Add observe fields at root for backward compat
                    field_context.update(value)
                elif isinstance(value, dict):
                    # Add agent namespace
                    field_context[key] = value
                else:
                    # Direct field (shouldn't happen in new format)
                    field_context[key] = value
        else:
            # LEGACY: Flat format (backward compatibility)
            field_context.update(contents)

    if loop_context:
        field_context['loop'] = loop_context
    if workflow_metadata:
        field_context['workflow'] = workflow_metadata

    return field_context
```

### Phase 2: Input/Output Signature Declaration

#### 2.1 Extend YAML Schema

**File:** `agent_actions/core/parser/config_schema.py`

```python
class InputSignature(BaseModel):
    """Explicit input signature declaration."""

    from_dependencies: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Map of dependency_name -> [fields to use from that dependency]"
    )
    from_observe: List[str] = Field(
        default_factory=list,
        description="Fields expected from observe directive"
    )
    allow_extra: bool = Field(
        default=True,
        description="Allow extra fields not in signature (for backward compat)"
    )

class OutputSignature(BaseModel):
    """Explicit output signature declaration."""

    schema_fields: List[str] = Field(
        default_factory=list,
        description="Fields from output_schema"
    )
    observe_fields: List[str] = Field(
        default_factory=list,
        description="Fields from observe directive"
    )
    enforce_strict: bool = Field(
        default=False,
        description="Fail if actual output doesn't match signature"
    )

class AgentConfig(BaseModel):
    """Agent configuration with input/output signatures."""

    # Existing fields...

    # NEW: Signature fields
    inputs: Optional[InputSignature] = Field(
        default=None,
        description="Explicit input signature (optional)"
    )
    outputs: Optional[OutputSignature] = Field(
        default=None,
        description="Explicit output signature (optional)"
    )
```

#### 2.2 Add Signature Validation

**File:** `agent_actions/agents/validators/signature_validator.py` (NEW)

```python
class SignatureValidator:
    """Validates input/output signatures match actual data."""

    @staticmethod
    def validate_input_signature(agent_name: str,
                                 declared_inputs: InputSignature,
                                 actual_contents: Dict) -> ValidationResult:
        """
        Validate actual input matches declared signature.

        Checks:
        1. All declared dependencies are present
        2. All declared fields from each dependency are available
        3. If allow_extra=False, no extra fields present
        """
        result = ValidationResult(agent_name=agent_name)

        # Extract available agent namespaces
        available_agents = {k for k in actual_contents.keys()
                          if k not in ['_observe', 'source', 'loop', 'workflow']}

        # Check each declared dependency
        for dep_name, expected_fields in declared_inputs.from_dependencies.items():
            if dep_name not in available_agents:
                result.errors.append(
                    SignatureError(
                        agent=agent_name,
                        dependency=dep_name,
                        message=f"Declared dependency '{dep_name}' not found",
                        available=list(available_agents)
                    )
                )
                continue

            # Check fields from this dependency
            actual_fields = set(actual_contents[dep_name].keys())
            expected = set(expected_fields)
            missing = expected - actual_fields

            if missing:
                result.errors.append(
                    SignatureError(
                        agent=agent_name,
                        dependency=dep_name,
                        message=f"Missing fields from '{dep_name}': {missing}",
                        available=list(actual_fields)
                    )
                )

        return result

    @staticmethod
    def validate_output_signature(agent_name: str,
                                  declared_outputs: OutputSignature,
                                  actual_output: Dict) -> ValidationResult:
        """
        Validate actual output matches declared signature.

        Checks:
        1. All declared schema_fields are produced
        2. All declared observe_fields are present
        3. If enforce_strict=True, no extra fields produced
        """
        result = ValidationResult(agent_name=agent_name)

        # Get actual schema fields
        actual_schema = set(actual_output.get(agent_name, {}).keys())
        declared_schema = set(declared_outputs.schema_fields)

        # Check for missing schema fields
        missing_schema = declared_schema - actual_schema
        if missing_schema:
            result.errors.append(
                SignatureError(
                    agent=agent_name,
                    message=f"Missing declared schema fields: {missing_schema}",
                    available=list(actual_schema)
                )
            )

        # If strict mode, check for undeclared fields
        if declared_outputs.enforce_strict:
            extra_schema = actual_schema - declared_schema
            if extra_schema:
                result.errors.append(
                    SignatureError(
                        agent=agent_name,
                        message=f"Undeclared schema fields produced: {extra_schema}",
                        hint="Set enforce_strict=false to allow extra fields"
                    )
                )

        return result
```

### Phase 3: Backward Compatibility

#### 3.1 Migration Strategy

**Option A: Gradual Migration (Recommended)**
```python
# Support both formats simultaneously
def _build_field_context(self, contents: Dict, ...) -> Dict:
    """Auto-detect format and handle both."""

    if self._is_namespaced_format(contents):
        # New format: {'agent': {...}, '_observe': {...}}
        return self._build_namespaced_context(contents, ...)
    else:
        # Legacy format: {'field': 'value', ...}
        return self._build_flat_context(contents, ...)

def _is_namespaced_format(self, contents: Dict) -> bool:
    """Detect if contents uses namespaced format."""
    # Check for agent namespaces (dict values that aren't special keys)
    return any(
        isinstance(v, dict) and k not in ['_observe', 'source', 'loop', 'workflow']
        for k, v in contents.items()
    )
```

**Option B: Feature Flag**
```yaml
# agent-actions.config.yml
features:
  agent_namespace_preservation: true  # Enable new format
  strict_signatures: false  # Don't enforce signatures yet
```

#### 3.2 Deprecation Timeline

1. **v2.1.0** - Add namespace preservation support (opt-in via feature flag)
2. **v2.2.0** - Enable by default, legacy format deprecated (warning logged)
3. **v3.0.0** - Remove legacy flat format support (breaking change)

### Phase 4: Documentation & Migration Guide

#### 4.1 User Documentation

**docs/field_referencing.md:**
```markdown
# Field Referencing Guide

## Namespace-Aware References

### Referencing Dependency Outputs

When an agent depends on another agent, you can reference its outputs:

```yaml
actions:
  - name: extractor
    schema: {summary: string, keywords: array}

  - name: analyzer
    dependencies: [extractor]
    prompt: "Analyze: {extractor.summary}"
```

### Referencing Observe Fields

Fields from `observe` are available at root level:

```yaml
actions:
  - name: processor
    observe: [id, url]
    prompt: "Processing {id} from {url}"
```

### Ambiguity Resolution

When multiple agents produce the same field name, use namespaces:

```yaml
actions:
  - name: agent_A
    schema: {score: number}

  - name: agent_B
    schema: {score: number}

  - name: combiner
    dependencies: [agent_A, agent_B]
    prompt: "Compare {agent_A.score} vs {agent_B.score}"
```
```

#### 4.2 Migration Guide

**docs/migration/namespace_preservation.md:**
```markdown
# Migrating to Namespace Preservation

## Breaking Changes in v3.0.0

### Data Structure Change

**Before (Flat):**
```python
contents = {
    'field1': 'from agent A',
    'field2': 'from agent B',
    'observed_field': 'from observe'
}
```

**After (Namespaced):**
```python
contents = {
    'agent_A': {
        'field1': 'from agent A'
    },
    'agent_B': {
        'field2': 'from agent B'
    },
    '_observe': {
        'observed_field': 'from observe'
    }
}
```

### Updating Custom Code

If you have custom processors or tools that access `contents`:

**Before:**
```python
def my_processor(contents):
    value = contents['field1']  # Direct access
```

**After:**
```python
def my_processor(contents):
    # Option 1: Access via namespace
    value = contents['agent_A']['field1']

    # Option 2: Use helper
    value = get_field(contents, 'agent_A', 'field1')

    # Option 3: Access observe fields (still at root for backward compat)
    observed = contents.get('observed_field')  # Works if in observe
```

### Testing Your Migration

```bash
# Enable feature flag to test new format
export AGENT_ACTIONS_NAMESPACE_PRESERVATION=true

# Run your workflows
agent-actions run my-workflow.yml

# Check for warnings about flat format usage
```
```

## Implementation Plan

### Milestone 1: Core Data Structure (2-3 weeks)
- [ ] Update `data_processor.py` to wrap outputs with agent namespace
- [ ] Update `data_generator.py` field context building to handle namespaces
- [ ] Add namespace detection and backward compatibility layer
- [ ] Update all internal pipeline code to preserve namespaces
- [ ] Add unit tests for namespace wrapping and unwrapping

### Milestone 2: Signature Declaration (1-2 weeks)
- [ ] Extend Pydantic schema with `InputSignature` and `OutputSignature`
- [ ] Implement `SignatureValidator` for input/output validation
- [ ] Integrate signature validation into config handler
- [ ] Add signature validation to CI/CD checks
- [ ] Write comprehensive tests for signature validation

### Milestone 3: Integration & Testing (2-3 weeks)
- [ ] Update `InputSignatureValidator` to work with namespaced data
- [ ] Fix all integration tests to use namespaced format
- [ ] Add new integration tests for `{agent.field}` references
- [ ] Test qanalabs-quiz-gen workflow with namespaces
- [ ] Performance testing (ensure no significant overhead)

### Milestone 4: Documentation & Migration Tools (1 week)
- [ ] Write migration guide
- [ ] Update all documentation with namespace examples
- [ ] Create migration validation tool
- [ ] Add namespace format checker for existing workflows
- [ ] Create example workflows demonstrating signatures

### Milestone 5: Backward Compatibility & Deprecation (1 week)
- [ ] Implement feature flag system
- [ ] Add deprecation warnings for flat format
- [ ] Create automated migration script
- [ ] Plan deprecation timeline
- [ ] Update changelog and release notes

**Total Estimated Time:** 7-10 weeks

## Testing Strategy

### Unit Tests

```python
class TestAgentNamespacePreservation:
    def test_wrap_agent_output_preserves_namespace(self):
        """Test agent output is wrapped with namespace."""
        processor = DataProcessor(...)

        agent_output = {'new_field': 'value'}
        observe_fields = {'id': '123', 'url': 'https://...'}

        wrapped = processor._wrap_with_namespace(
            agent_name='extractor',
            agent_output=agent_output,
            observe_fields=observe_fields
        )

        assert wrapped == {
            'extractor': {'new_field': 'value'},
            '_observe': {'id': '123', 'url': 'https://...'}
        }

    def test_field_context_building_with_namespaces(self):
        """Test field context correctly built from namespaced data."""
        contents = {
            'agent_A': {'field1': 'value1'},
            'agent_B': {'field2': 'value2'},
            '_observe': {'id': '123'}
        }

        field_context = DataGenerator._build_field_context(
            contents, source_content={'text': 'source'}
        )

        assert field_context == {
            'source': {'text': 'source'},
            'agent_A': {'field1': 'value1'},
            'agent_B': {'field2': 'value2'},
            'id': '123'  # Observe at root for backward compat
        }

    def test_backward_compatibility_flat_format(self):
        """Test legacy flat format still works."""
        contents = {
            'field1': 'value1',
            'field2': 'value2'
        }

        field_context = DataGenerator._build_field_context(contents, None)

        # Should pass through as-is
        assert field_context == contents
```

### Integration Tests

```python
class TestAgentFieldReferencingE2E:
    def test_agent_field_reference_in_real_workflow(self):
        """Test {agent.field} works end-to-end."""

        config = {
            'actions': [
                {
                    'name': 'extractor',
                    'schema': {'summary': 'string'},
                    'prompt': 'Extract summary from {source.content}'
                },
                {
                    'name': 'analyzer',
                    'dependencies': ['extractor'],
                    'prompt': 'Analyze: {extractor.summary}'
                }
            ]
        }

        result = run_workflow(config, source_data={'content': 'test text'})

        # Verify extractor.summary was resolved in analyzer prompt
        assert 'test summary' in result['analyzer']['prompt_used']

    def test_multiple_agents_same_field_name(self):
        """Test namespace resolution when multiple agents produce same field."""

        config = {
            'actions': [
                {'name': 'agent_A', 'schema': {'score': 'number'}},
                {'name': 'agent_B', 'schema': {'score': 'number'}},
                {
                    'name': 'combiner',
                    'dependencies': ['agent_A', 'agent_B'],
                    'prompt': 'A: {agent_A.score}, B: {agent_B.score}'
                }
            ]
        }

        result = run_workflow(config, ...)

        # Verify both scores correctly resolved
        assert 'A: 0.8' in result['combiner']['prompt_used']
        assert 'B: 0.9' in result['combiner']['prompt_used']
```

### Validation Tests

```python
class TestSignatureValidation:
    def test_input_signature_validation_missing_dependency(self):
        """Test error when declared dependency not available."""

        agent_config = {
            'name': 'analyzer',
            'inputs': {
                'from_dependencies': {
                    'extractor': ['summary', 'keywords']
                }
            }
        }

        actual_contents = {
            'other_agent': {'data': '...'}  # extractor missing!
        }

        result = SignatureValidator.validate_input_signature(
            'analyzer', agent_config['inputs'], actual_contents
        )

        assert result.has_errors()
        assert 'extractor' in str(result.errors[0])

    def test_output_signature_validation_strict_mode(self):
        """Test strict mode catches undeclared output fields."""

        declared_outputs = {
            'schema_fields': ['field1', 'field2'],
            'enforce_strict': True
        }

        actual_output = {
            'agent': {
                'field1': 'value1',
                'field2': 'value2',
                'field3': 'undeclared!'  # Extra field
            }
        }

        result = SignatureValidator.validate_output_signature(
            'agent', declared_outputs, actual_output
        )

        assert result.has_errors()
        assert 'field3' in str(result.errors[0])
```

## Success Criteria

### Must Have (Blocking Release)
- ✅ `{agent.field}` references work in runtime execution
- ✅ Validation and runtime aligned (no false positives)
- ✅ Backward compatibility with existing workflows
- ✅ All existing tests pass
- ✅ qanalabs-quiz-gen workflow runs successfully with `{create_new_clusters.bloom_details}`
- ✅ Zero performance regression (< 5% overhead)

### Should Have
- ✅ Input/output signature declaration working
- ✅ Signature validation integrated into CLI
- ✅ Migration guide completed
- ✅ Feature flag system implemented
- ✅ Example workflows with signatures

### Nice to Have
- ⭐ Automated migration tool
- ⭐ Visual workflow diagram showing field flow
- ⭐ IDE autocomplete for field references
- ⭐ Runtime introspection API for debugging

## Related Issues

- **#429** - Implement Unified Field Referencing Pattern (dependency)
- **#430** - Input Signature Validation (related validation)
- **#435** - Fix Input Signature Validation for Pydantic Fields (PR - partial fix)
- **#436** - File-Level Processing Missing source_content (runtime bug - fixed)

## Breaking Changes

### v3.0.0 Breaking Changes

1. **Data Structure:**
   - `contents` dict now namespaced: `{'agent': {...}, '_observe': {...}}`
   - Custom processors/tools must update field access

2. **API Changes:**
   - `process_item()` now requires `agent_name` parameter
   - `field_context` structure changed (namespaced)

3. **Configuration:**
   - Workflows using undeclared dependencies will fail with `strict_signatures=true`
   - Output fields not in schema will fail with `enforce_strict=true`

### Migration Support

- Feature flag to enable/disable namespace preservation
- Deprecation warnings in v2.x versions
- Automated migration tool provided
- 6-month deprecation period before v3.0.0

## Questions for Discussion

1. **Backward Compatibility:** Should we support flat format indefinitely via feature flag, or enforce migration?
2. **Default Behavior:** Should signature declaration be required or optional?
3. **Observe Namespace:** Should observe fields have their own namespace or stay at root level?
4. **Performance:** Is the overhead of namespace wrapping/unwrapping acceptable?
5. **Tool Actions:** How do tool actions (kind: tool) fit into namespace preservation?

## Success Metrics

- **Functionality:** 100% of `{agent.field}` references work
- **Performance:** < 5% overhead from namespace wrapping
- **Migration:** 90% of existing workflows work without changes (backward compat)
- **Developer Experience:** < 5 minutes to understand and use signatures
- **Error Messages:** 100% of signature errors have clear, actionable messages
