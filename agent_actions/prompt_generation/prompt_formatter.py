"""
Module for prompt formatting and loading.

This module provides unified prompt loading and formatting functionality used by
both batch and realtime modes (Phase 3 of issue #492).

## Overview

PromptFormatter handles two key operations:
1. **Prompt Loading** (`get_raw_prompt`) - Loads prompts from config or files
2. **Prompt Formatting** (`format_prompt`) - Replaces field references in prompts

## Shared Usage

**All Modes** (batch_service.py, data_generator.py, agent_builder.py):
```python
from agent_actions.prompt_generation.prompt_formatter import PromptFormatter

# Load raw prompt (handles $ prefix for external files)
raw_prompt = PromptFormatter.get_raw_prompt(agent_config)

# Format prompt with field references
formatted_prompt = PromptFormatter.format_prompt(raw_prompt, field_context)
```

## Prompt Loading

The `get_raw_prompt()` method handles three scenarios:

1. **Direct prompt in config**:
```python
agent_config = {
    'prompt': 'Analyze the following data: {source.content}'
}
# Returns: 'Analyze the following data: {source.content}'
```

2. **External prompt file** (using `$` prefix):
```python
agent_config = {
    'prompt': '$my_prompts.analysis_prompt'
}
# Loads from: ./prompt_store/my_prompts.md
# Looks for: {analysis_prompt} ... {end_prompt} block
```

3. **Default prompt** (if empty):
```python
agent_config = {}
# Returns: 'Process the following content: {content}'
```

## Error Handling

- Validates prompt exists and is properly formatted
- Raises `PromptValidationError` with context on failure
- Includes operation name and config details in error

## Benefits

1. **Single Source of Truth** - Prompt loading logic in ONE place
2. **Consistent Behavior** - All modes use identical logic
3. **Default Fallback** - Prevents unexpected empty prompts
4. **Centralized Error Handling** - Better error messages
5. **Fixed Typo** - Phase 3 fixed error handling bug (prompt_config → agent_config)

## Improvements in Phase 3

- Fixed typo in error handling context
- Added default fallback to agent_builder.py (previously missing)
- Eliminated ~20 lines of duplicated code across 5 files
- Consistent behavior across all batch and realtime modes

## Related Components

- **PromptLoader**: Handles external file loading from prompt_store/
- **PromptUtils**: Handles field reference replacement ({reference.field})
- **ContextScopeProcessor**: Builds field_context for prompt formatting

## See Also

- Architecture docs: `dev_artefacts/BATCH_REALTIME_ARCHITECTURE.md`
- Prompt store: `./prompt_store/`
- Issue: https://github.com/Muizzkolapo/agent-actions/issues/492
"""
from agent_actions.prompt_generation.prompt_handler import PromptLoader
from agent_actions.utilities.constants import PROMPT_KEY
from agent_actions.prompt_generation.prompt_utils import PromptUtils

class PromptFormatter:
    """Handles prompt formatting and loading (Single Responsibility)."""

    @staticmethod
    def get_raw_prompt(agent_config):
        """
        Retrieve and process the raw prompt from the agent configuration.
        
        Parameters:
            agent_config: Configuration containing prompt information
            
        Returns:
            Raw prompt string
            
        Raises:
            ValueError: If prompt retrieval fails
        """
        try:
            raw_prompt = agent_config.get(PROMPT_KEY, '')
            if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
                raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
            if not raw_prompt:
                raw_prompt = 'Process the following content: {content}'
            return raw_prompt
        except Exception as e:
            # pylint: disable=import-outside-toplevel
            from agent_actions.errors import PromptValidationError  # New modular pattern!
            raise PromptValidationError(
                f'Failed to get raw prompt: {str(e)}',
                context={
                    'field': 'raw_prompt',
                    'agent_config': str(agent_config),
                    'operation': 'get_raw_prompt'
                },
                cause=e
            ) from e

    @staticmethod
    def format_prompt(raw_prompt, field_context=None):
        """
        Replace {reference.field} patterns in the prompt.

        Parameters:
            raw_prompt: Template prompt with field references
            field_context: Dict with field references (source, agent outputs, loop, workflow)

        Returns:
            Formatted prompt with all {reference.field} patterns replaced

        Raises:
            ValueError: If prompt formatting fails
        """
        try:
            if field_context:
                return PromptUtils.replace_field_references(raw_prompt, field_context)
            return raw_prompt
        except Exception as e:
            # pylint: disable=import-outside-toplevel
            from agent_actions.errors import PromptValidationError  # New modular pattern!
            raise PromptValidationError(
                f'Failed to format prompt: {str(e)}',
                context={
                    'field': 'formatted_prompt',
                    'raw_prompt': str(raw_prompt)[:100],
                    'operation': 'format_prompt'
                },
                cause=e
            ) from e
