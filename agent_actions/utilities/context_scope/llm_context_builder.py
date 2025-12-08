"""
LLM Context Builder - Unified context building for batch and realtime modes.

This module provides a unified interface for building LLM context that handles:
- Starting with base context (row_content in batch, processed_context in realtime)
- Removing dropped fields (context_scope.drop)
- Adding observed fields (context_scope.observe)

The builder preserves the distinct approaches used by each mode:
- Batch mode: Manual dict operations (pop fields, update with observe)
- Realtime mode: DataTransformer for field removal, dict merge for observe

This eliminates ~40 lines of code duplication (Phase 2 of issue #492).

## Overview

LLMContextBuilder provides two static methods for building LLM context:
1. `build_llm_context_for_batch()` - Batch mode context building
2. `build_llm_context_for_realtime()` - Realtime mode context building

Both methods handle the same core operations but use mode-specific implementations
to maintain backward compatibility and existing behavior.

## Shared Usage

**Batch Mode** (`batch_service.py`):
```python
from agent_actions.utilities.context_scope.llm_context_builder import LLMContextBuilder

# Build LLM context from row content
llm_full_context = LLMContextBuilder.build_llm_context_for_batch(
    row_content=row_content,           # Current row data
    llm_context=llm_context,           # Fields from context_scope.observe
    context_scope=context_scope        # Configuration with drop/observe directives
)

# Use for prompt injection
formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
    formatted_prompt,
    tools_path,
    json.dumps(llm_full_context, ensure_ascii=False),
    agent_config=agent_config
)
```

**Realtime Mode** (`processor_helpers.py`):
```python
from agent_actions.utilities.context_scope.llm_context_builder import LLMContextBuilder

# Extract content from nested structure
if isinstance(context, dict) and 'content' in context:
    processed_context = context['content']
else:
    processed_context = context

# Build LLM context
processed_context = LLMContextBuilder.build_llm_context_for_realtime(
    processed_context=processed_context,
    llm_additional_context=llm_additional_context,  # From context_scope.observe
    context_scope=context_scope
)

# Pass to agent builder
response = agent_builder.create_dynamic_agent(
    agent_config,
    agent_name,
    processed_context,  # Already has drops applied and observe merged
    formatted_prompt
)
```

## Context Scope Operations

### Drop Fields (`context_scope.drop`)

Removes specified fields from the context before sending to LLM:

```python
context_scope = {
    'drop': ['source.api_key', 'source.password']  # Field references to remove
}

# Batch mode: Uses dict.pop(field_name, None)
# Realtime mode: Uses DataTransformer.remove_schema_objects(context, fields)
```

### Observe Fields (`context_scope.observe`)

Adds fields from previous actions or external sources:

```python
# Fields from context_scope.observe are passed as llm_context/llm_additional_context
llm_context = {
    'metadata': {'source': 'research'},  # From previous action
    'entities': ['entity1', 'entity2']   # From previous action
}

# These are merged into the base context
# Batch mode: Uses dict.update(llm_context)
# Realtime mode: Uses dict spread {**processed_context, **llm_additional_context}
```

## Mode-Specific Implementations

### Why Two Methods?

The builder has separate methods because batch and realtime use fundamentally
different approaches for field removal:

**Batch Mode (`dict.pop()`)**:
- Simple and direct
- In-place mutation of copied dict
- Matches existing batch_service.py behavior

**Realtime Mode (`DataTransformer.remove_schema_objects()`)**:
- More sophisticated field removal
- Handles nested structures
- Integrates with existing realtime infrastructure
- Matches existing processor_helpers.py behavior

### Preserving Backward Compatibility

Rather than forcing both modes to use the same implementation, we preserve
the existing approaches to ensure:
- Zero breaking changes
- Existing behavior maintained exactly
- No subtle bugs from implementation changes

## Benefits

1. **Single Source of Truth** - Context building logic in ONE place per mode
2. **Clear Separation** - Batch vs realtime approaches are explicit
3. **Comprehensive Testing** - 20 unit tests covering all scenarios
4. **Well Documented** - Usage examples for both modes
5. **Type Hints** - All parameters and return values typed

## Edge Cases Handled

- **None row_content** - Returns empty dict with llm_context merged
- **Non-dict row_content** - Returns empty dict with llm_context merged
- **None llm_context** - Skips observe merge
- **Invalid field references** - Skipped silently (backward compatible)
- **Empty context_scope** - Returns base context unchanged
- **Observe field overwrites** - Observe fields take precedence

## Related Components

- **ContextScopeProcessor**: Builds field_context and extracts llm_context/observe fields
- **DataTransformer**: Used by realtime mode for field removal
- **PromptUtils**: Uses llm_full_context for prompt injection

## See Also

- Architecture docs: `dev_artefacts/BATCH_REALTIME_ARCHITECTURE.md`
- Tests: `tests/utilities/test_llm_context_builder.py`
- Issue: https://github.com/Muizzkolapo/agent-actions/issues/492
"""

from typing import Dict, Any, Optional
from agent_actions.utilities.context_scope.context_scope_processor import ContextScopeProcessor
from agent_actions.preprocessing.transformation.data_transformer import DataTransformer


class LLMContextBuilder:
    """
    Unified builder for LLM context across batch and realtime modes.

    Handles the core logic of:
    1. Starting with base context
    2. Applying context_scope.drop directives
    3. Merging context_scope.observe fields

    Different modes use different implementation approaches:
    - Batch: Uses dict.pop() for drops, dict.update() for observe
    - Realtime: Uses DataTransformer.remove_schema_objects() for drops, dict merge for observe
    """

    @staticmethod
    def build_llm_context_for_batch(
        row_content: Dict[str, Any],
        llm_context: Dict[str, Any],
        context_scope: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build LLM context for batch mode.

        This method implements the exact logic from batch_service.py:
        1. Start with row_content (copy to avoid mutation)
        2. Remove dropped fields using dict.pop() (context_scope.drop)
        3. Add observed fields using dict.update() (from llm_context)

        Args:
            row_content: Base content dict (the current row in batch mode)
            llm_context: Fields from context_scope.observe (already extracted by apply_context_scope)
            context_scope: Optional context scope configuration with 'drop' directive

        Returns:
            Dict ready for JSON serialization and LLM invocation

        Example:
            >>> row_content = {'text': 'data', 'api_key': 'secret', 'id': '123'}
            >>> llm_context = {'metadata': {'source': 'research'}}
            >>> context_scope = {'drop': ['source.api_key']}
            >>> result = LLMContextBuilder.build_llm_context_for_batch(
            ...     row_content, llm_context, context_scope
            ... )
            >>> # Result: {'text': 'data', 'id': '123', 'metadata': {'source': 'research'}}
            >>> # (api_key removed, metadata added)
        """
        # Start with copy of row content (avoid mutating original)
        if not isinstance(row_content, dict):
            llm_full_context = {}
        else:
            llm_full_context = row_content.copy()

        # Remove dropped fields (context_scope.drop)
        if context_scope and context_scope.get('drop'):
            for field_ref in context_scope.get('drop', []):
                try:
                    # Parse field reference (e.g., 'source.api_key' -> 'api_key')
                    _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                    llm_full_context.pop(field_name, None)
                except ValueError:
                    # Invalid field reference, skip silently (backward compatible)
                    continue

        # Add observed fields from llm_context (context_scope.observe)
        if llm_context:
            llm_full_context.update(llm_context)

        return llm_full_context

    @staticmethod
    def build_llm_context_for_realtime(
        processed_context: Dict[str, Any],
        llm_additional_context: Optional[Dict[str, Any]],
        context_scope: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build LLM context for realtime mode.

        This method implements the exact logic from processor_helpers.py:
        1. Start with processed_context
        2. Remove dropped fields using DataTransformer.remove_schema_objects() (context_scope.drop)
        3. Merge llm_additional_context using dict spread (context_scope.observe)

        Args:
            processed_context: Base context dict (already extracted from nested structure)
            llm_additional_context: Fields from context_scope.observe
            context_scope: Optional context scope configuration with 'drop' directive

        Returns:
            Dict ready to pass to create_dynamic_agent()

        Example:
            >>> processed_context = {'text': 'data', 'api_key': 'secret', 'id': '123'}
            >>> llm_additional_context = {'metadata': {'source': 'research'}}
            >>> context_scope = {'drop': ['source.api_key']}
            >>> result = LLMContextBuilder.build_llm_context_for_realtime(
            ...     processed_context, llm_additional_context, context_scope
            ... )
            >>> # Result: {'text': 'data', 'id': '123', 'metadata': {'source': 'research'}}
            >>> # (api_key removed via DataTransformer, metadata merged)
        """
        # Return unchanged if not a dict
        if not isinstance(processed_context, dict):
            return processed_context

        result_context = processed_context

        # Apply context_scope.drop field filtering using DataTransformer
        if context_scope and context_scope.get('drop'):
            # Extract field names from context_scope.drop
            drop_fields = []
            for field_ref in context_scope.get('drop', []):
                try:
                    # Parse field reference (e.g., 'source.api_key' -> 'api_key')
                    _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                    drop_fields.append(field_name)
                except ValueError:
                    # Invalid field reference, skip silently (backward compatible)
                    continue

            # Remove dropped fields from context using DataTransformer
            if drop_fields:
                result_context = DataTransformer.remove_schema_objects(result_context, drop_fields)

        # Merge context_scope.observe fields into context JSON (dict spread)
        if llm_additional_context and isinstance(result_context, dict):
            result_context = {**result_context, **llm_additional_context}

        return result_context
