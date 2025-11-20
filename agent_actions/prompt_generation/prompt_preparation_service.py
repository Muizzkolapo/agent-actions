"""
Prompt Preparation Service - Unified prompt preparation for batch and realtime modes.

This service provides a single point of truth for preparing prompts with field context,
historical data, context_scope transformations, and few-shot samples.

Used by BOTH online (DataGenerator) and batch (BatchService) modes to ensure
consistent behavior and eliminate code duplication.

## Overview

PromptPreparationService orchestrates the complete prompt preparation pipeline:
1. Load raw prompt template
2. Build field context with historical node loading
3. Apply context_scope transformations (observe/drop/passthrough)
4. Build LLM context (mode-specific)
5. Replace field references ({action.field})
6. Inject function outputs (batch mode only)
7. Append few-shot samples

## Usage

**Online Mode** (DataGenerator):
```python
from agent_actions.prompt_generation.prompt_preparation_service import (
    PromptPreparationService
)

result = PromptPreparationService.prepare_prompt_with_context(
    agent_config=agent_config,
    agent_name=agent_name,
    contents=contents,
    mode='realtime',
    agent_indices=agent_indices,
    dependency_configs=dependency_configs,
    source_content=source_content,
    loop_context=loop_context,
    workflow_metadata=workflow_metadata,
    current_item=current_item,
    file_path=file_path
)

# Use result
formatted_prompt = result.formatted_prompt
llm_context = result.llm_context
passthrough_fields = result.passthrough_fields
```

**Batch Mode** (BatchService):
```python
result = PromptPreparationService.prepare_prompt_with_context(
    agent_config=agent_config,
    agent_name=agent_name,
    contents=row_content,
    mode='batch',
    agent_indices=agent_indices,
    dependency_configs=dependency_configs,
    source_content=row_content,
    current_item=context_map[custom_id],
    file_path=file_path_for_history,
    tools_path=tools_path
)

# Create batch task
task = {
    'target_id': custom_id,
    'content': result.llm_context,
    'prompt': result.formatted_prompt
}
```

## Benefits

1. **Single Point of Change** - Prompt preparation logic in ONE place
2. **Guaranteed Parity** - Batch and realtime cannot diverge
3. **Comprehensive Testing** - Test service in isolation
4. **Better Debugging** - Metadata provides visibility
5. **Bug Fixes** - Few-shot samples now work in batch mode

## Related Components

- **PromptFormatter**: Loads raw prompt templates
- **ContextScopeProcessor**: Builds field context and applies context_scope
- **LLMContextBuilder**: Builds LLM context (mode-specific)
- **PromptUtils**: Field reference substitution and function injection
- **SampleEnricher**: Appends few-shot samples

## See Also

- Implementation plan: `dev_artefacts/implementations/issue_487_prompt_preparation_service.jsonc`
- Issue: https://github.com/Muizzkolapo/agent-actions/issues/487
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass

from agent_actions.preprocessing.prompt_formatter import PromptFormatter
from agent_actions.preprocessing.prompt_utils import PromptUtils
from agent_actions.preprocessing.sample_enricher import SampleEnricher
from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
from agent_actions.utilities.llm_context_builder import LLMContextBuilder
from agent_actions.utilities.static_data_loader import StaticDataLoader, StaticDataLoadError

logger = logging.getLogger(__name__)


@dataclass
class PromptPreparationResult:
    """
    Result of prompt preparation.

    Attributes:
        formatted_prompt: Fully rendered prompt ready for LLM (with field references replaced,
                         function outputs injected, and few-shot samples appended)
        llm_context: Full context dict for LLM (JSON serializable), includes:
                    - Base content (row_content in batch, processed_context in realtime)
                    - Fields from context_scope.observe
                    - Minus fields from context_scope.drop
        passthrough_fields: Fields to merge into output (from context_scope.passthrough)
        metadata: Debug information including:
                 - field_context_keys: Keys in field_context before context_scope
                 - observe_fields: Fields added from context_scope.observe
                 - drop_fields: Fields removed from context_scope.drop
                 - passthrough_fields: Fields marked for passthrough
                 - mode: Processing mode used (batch or realtime)
    """
    formatted_prompt: str
    llm_context: Dict[str, Any]
    passthrough_fields: Dict[str, Any]
    metadata: Dict[str, Any]


class PromptPreparationService:
    """
    Unified service for preparing prompts across batch and realtime modes.

    This service orchestrates all prompt preparation steps to ensure consistent
    behavior between online (DataGenerator) and batch (BatchService) modes.

    The service is the SINGLE POINT OF TRUTH for prompt preparation. Both modes
    MUST use this service to prevent divergent behavior.
    """

    @staticmethod
    def prepare_prompt_with_context(
        agent_config: Dict[str, Any],
        agent_name: str,
        contents: Dict[str, Any],
        *,
        mode: Literal['batch', 'realtime'] = 'realtime',
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,
        source_content: Optional[Any] = None,
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None,
        tools_path: Optional[str] = None
    ) -> PromptPreparationResult:
        """
        Prepare prompt with all transformations applied.

        This method orchestrates the complete prompt preparation pipeline:
        1. Load raw prompt template
        2. Build field context with historical node loading
        3. Apply context_scope transformations (observe/drop/passthrough)
        4. Build LLM context (mode-specific)
        5. Replace field references ({action.field})
        6. Inject function outputs (batch mode only)
        7. Append few-shot samples

        Args:
            agent_config: Agent configuration dict
            agent_name: Name of the agent
            contents: Content dict to process (row_content in batch, contents in realtime)
            mode: Processing mode - 'batch' or 'realtime' (default: 'realtime')
            agent_indices: Optional dict mapping agent names to node indices
            dependency_configs: Optional dict mapping dependency names to their configs
            source_content: Optional source content for {source.field} references
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references
            current_item: Optional current item dict containing lineage and source_guid
            file_path: Optional file path for constructing historical node paths
            tools_path: Optional path to tools directory (for function injection in batch mode)

        Returns:
            PromptPreparationResult containing:
            - formatted_prompt: Fully rendered prompt
            - llm_context: Full context for LLM
            - passthrough_fields: Fields to merge into output
            - metadata: Debug information

        Example:
            >>> # Realtime mode
            >>> result = PromptPreparationService.prepare_prompt_with_context(
            ...     agent_config={'prompt': 'Validate {action.data}'},
            ...     agent_name='validator',
            ...     contents={'data': 'test'},
            ...     mode='realtime'
            ... )
            >>> print(result.formatted_prompt)  # 'Validate test'

            >>> # Batch mode
            >>> result = PromptPreparationService.prepare_prompt_with_context(
            ...     agent_config={'prompt': 'Process {source.text}'},
            ...     agent_name='processor',
            ...     contents={'text': 'batch data'},
            ...     mode='batch',
            ...     tools_path='/path/to/tools'
            ... )
        """
        logger.info(f"Preparing prompt for agent '{agent_name}' in {mode} mode")

        # Initialize defaults
        agent_indices = agent_indices or {}
        dependency_configs = dependency_configs or {}

        # Step 1: Load raw prompt template
        raw_prompt = PromptFormatter.get_raw_prompt(agent_config)
        logger.debug(f"Loaded raw prompt (length: {len(raw_prompt)})")

        # Step 2: Build field context with historical node loading
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=contents if isinstance(contents, dict) else {},
            agent_name=agent_name,
            agent_config=agent_config,
            agent_indices=agent_indices,
            dependency_configs=dependency_configs,
            source_content=source_content,
            loop_context=loop_context,
            workflow_metadata=workflow_metadata,
            current_item=current_item,
            file_path=file_path
        )
        logger.debug(f"Built field context with {len(field_context)} top-level keys")

        # Step 2.5: Load static data files if configured
        context_scope = agent_config.get('context_scope', {})
        static_data = {}

        if context_scope and context_scope.get('static_data'):
            try:
                logger.info(f"[STATIC_DATA_LOAD] Starting static data loading...")
                # Determine static_data directory from workflow config path
                static_data_dir = PromptPreparationService._determine_static_data_dir(
                    agent_config.get('workflow_config_path')
                )
                logger.info(f"[STATIC_DATA_LOAD] Static data directory: {static_data_dir}")

                # Load static data
                static_data_loader = StaticDataLoader(static_data_dir=static_data_dir)
                static_data = static_data_loader.load_static_data(
                    context_scope.get('static_data', {})
                )

                logger.info(
                    f"[STATIC_DATA_LOAD] Loaded {len(static_data)} static data files: "
                    f"{list(static_data.keys())}"
                )
                logger.info(f"[STATIC_DATA_LOAD] Static data keys: {list(static_data.keys())}")
            except StaticDataLoadError as e:
                logger.error(f"Failed to load static data: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error loading static data: {e}")
                raise StaticDataLoadError(
                    f"Failed to load static data: {str(e)}",
                    context={
                        'agent_name': agent_name,
                        'error': str(e),
                        'error_type': 'unexpected_static_data_error'
                    },
                    cause=e
                )

        # Step 3: Apply context_scope transformations (observe/drop/passthrough)
        if context_scope:
            prompt_context, llm_additional_context, passthrough_fields = \
                ContextScopeProcessor.apply_context_scope(
                    field_context,
                    context_scope,
                    static_data=static_data  # Pass static data to processor
                )
            logger.debug(
                f"Applied context_scope: "
                f"observe={len(llm_additional_context)}, "
                f"passthrough={len(passthrough_fields)}, "
                f"static_data={len(static_data)}"
            )
        else:
            # No context_scope: use field_context as-is for backward compatibility
            prompt_context = field_context
            llm_additional_context = {}
            passthrough_fields = {}
            logger.debug("No context_scope configured, using field_context as-is")

        # Step 4: Build LLM context (mode-specific)
        llm_context = PromptPreparationService._build_llm_context(
            mode=mode,
            contents=contents,
            llm_additional_context=llm_additional_context,
            context_scope=context_scope
        )
        logger.debug(f"Built LLM context for {mode} mode with {len(llm_context)} keys")

        # Step 5: Replace field references ({action.field})
        if prompt_context:
            formatted_prompt = PromptUtils.replace_field_references(raw_prompt, prompt_context)
            logger.debug("Replaced field references in prompt")
        else:
            formatted_prompt = raw_prompt
            logger.debug("No prompt_context, using raw prompt")

        # Step 6: Inject function outputs (batch mode only)
        if mode == 'batch' and tools_path:
            # In batch mode, inject llm_context as JSON for dispatch_task() functions
            formatted_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
                formatted_prompt,
                tools_path,
                json.dumps(llm_context, ensure_ascii=False),
                agent_config=agent_config
            )
            logger.debug("Injected function outputs (batch mode)")

        # Step 7: Append few-shot samples
        formatted_prompt = SampleEnricher.append_few_shot_samples(
            formatted_prompt,
            agent_config,
            agent_name
        )
        logger.debug("Appended few-shot samples")

        # Build metadata for debugging
        metadata = {
            'mode': mode,
            'field_context_keys': list(field_context.keys()),
            'observe_fields': list(llm_additional_context.keys()),
            'passthrough_fields': list(passthrough_fields.keys()),
            'drop_fields': context_scope.get('drop', []) if context_scope else [],
            'prompt_length': len(formatted_prompt),
            'llm_context_keys': list(llm_context.keys()) if isinstance(llm_context, dict) else []
        }

        logger.info(
            f"Prompt preparation complete for '{agent_name}': "
            f"prompt_length={metadata['prompt_length']}, "
            f"llm_context_keys={len(metadata['llm_context_keys'])}"
        )

        return PromptPreparationResult(
            formatted_prompt=formatted_prompt,
            llm_context=llm_context,
            passthrough_fields=passthrough_fields,
            metadata=metadata
        )

    @staticmethod
    def _build_llm_context(
        mode: str,
        contents: Dict[str, Any],
        llm_additional_context: Dict[str, Any],
        context_scope: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build the complete LLM context (mode-specific).

        This method delegates to the appropriate LLMContextBuilder method based on mode.

        Args:
            mode: Processing mode ('batch' or 'realtime')
            contents: Base content dict (row_content in batch, processed_context in realtime)
            llm_additional_context: Fields from context_scope.observe
            context_scope: Optional context scope configuration

        Returns:
            Dict ready for JSON serialization and LLM invocation

        Raises:
            ValueError: If mode is invalid
        """
        # Ensure contents is a dict (handle None or non-dict gracefully)
        safe_contents = contents if isinstance(contents, dict) else {}

        if mode == 'batch':
            # Batch mode: Start with row_content, remove drops, add observes
            return LLMContextBuilder.build_llm_context_for_batch(
                row_content=safe_contents,
                llm_context=llm_additional_context,
                context_scope=context_scope
            )
        elif mode == 'realtime':
            # Realtime mode: Start with processed_context, use DataTransformer for drops
            result = LLMContextBuilder.build_llm_context_for_realtime(
                processed_context=safe_contents,
                llm_additional_context=llm_additional_context,
                context_scope=context_scope
            )
            # Ensure result is always a dict (DataTransformer might return non-dict)
            return result if isinstance(result, dict) else {}
        else:
            raise ValueError(f"Invalid mode '{mode}'. Must be 'batch' or 'realtime'.")

    @staticmethod
    def _determine_static_data_dir(workflow_config_path: Optional[str]) -> Path:
        """
        Determine static_data/ or seed/ directory for loading static data files.

        Args:
            workflow_config_path: Path to workflow config file (from agent_config['workflow_config_path'])

        Returns:
            Path to static_data/ or seed/ directory

        Raises:
            StaticDataLoadError: If neither static_data/ nor seed/ folder exists
        """
        # Determine workflow root directory
        if not workflow_config_path:
            base_dir = Path.cwd()
        else:
            file_path_obj = Path(workflow_config_path)

            # If config file is in agent_config/ subdirectory, go up one level
            if file_path_obj.parent.name == 'agent_config':
                base_dir = file_path_obj.parent.parent
            else:
                base_dir = file_path_obj.parent

        logger.debug(f"Determined workflow base directory: {base_dir}")

        # Check for static_data/ folder (preferred)
        static_data_dir = base_dir / 'static_data'
        if static_data_dir.exists() and static_data_dir.is_dir():
            logger.debug(f"Found static_data/ folder: {static_data_dir}")
            return static_data_dir

        # Check for seed/ folder (alternative)
        seed_dir = base_dir / 'seed'
        if seed_dir.exists() and seed_dir.is_dir():
            logger.debug(f"Found seed/ folder: {seed_dir}")
            return seed_dir

        # Neither exists - raise error
        logger.error(
            f"Static data directory not found. Checked: {static_data_dir}, {seed_dir}"
        )
        raise StaticDataLoadError(
            f"Static data directory not found. Create '{static_data_dir}' "
            f"or '{seed_dir}' folder to store static data files.",
            context={
                'workflow_dir': str(base_dir),
                'checked_paths': [str(static_data_dir), str(seed_dir)],
                'error_type': 'missing_static_data_directory'
            }
        )


# Global instance for convenience (optional - service is stateless)
_global_service = None


def get_prompt_preparation_service() -> PromptPreparationService:
    """
    Get the global PromptPreparationService instance.

    Note: The service is stateless, so this is just for convenience.
    You can also call PromptPreparationService methods directly.
    """
    global _global_service
    if _global_service is None:
        _global_service = PromptPreparationService()
    return _global_service
