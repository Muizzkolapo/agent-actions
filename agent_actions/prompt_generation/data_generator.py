"""Module for generating data using agents."""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.utilities.processor.processor_helpers import (
    run_dynamic_agent,
    evaluate_guard_condition,
)
from agent_actions.configuration.interfaces import IGenerator, ProcessingMode
from agent_actions.orchestration.dependency_injection import registry
from agent_actions.utilities.field_resolution.evaluation_context_provider import (
    EvaluationContextProvider,
    ContextBuildConfig,
)
from agent_actions.prompt_generation.prompt_preparation_service import PromptPreparationService
from agent_actions.utilities.tools_resolver import resolve_tools_path
from agent_actions.errors import GenerationError

logger = logging.getLogger(__name__)


@dataclass
class GuardEvaluationContext:
    """Context for early guard evaluation."""

    contents: Any
    current_item: Optional[Dict] = None
    file_path: Optional[str] = None
    source_content: Optional[Any] = None
    loop_context: Optional[Dict] = None
    workflow_metadata: Optional[Dict] = None


@registry.register_generator("data_generator")
class DataGenerator(IGenerator):
    """Handles agent creation and data generation (Single Responsibility)."""

    def __init__(
        self,
        agent_config: AgentEntryDict,
        agent_name: str,
        dependency_configs: Optional[Dict[str, AgentEntryDict]] = None,
        agent_indices: Optional[Dict[str, int]] = None,
    ):
        """
        Initialize the data generator.

        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            dependency_configs: Optional dict mapping dependency names to their configs.
                              Used to build namespaced field_context for {agent.field} references.
            agent_indices: Optional dict mapping agent names to their node indices.
                         Used for loading historical node data via {action_name.field} references.
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.dependency_configs = dependency_configs or {}
        self.agent_indices = agent_indices or {}

    def _has_guard_condition(self) -> bool:
        """Check if agent has any guard condition configured."""
        return bool(
            self.agent_config.get("where_clause") or self.agent_config.get("conditional_clause")
        )

    def _evaluate_guard_early(self, context: GuardEvaluationContext) -> Tuple[bool, Optional[str]]:
        """
        Evaluate guard conditions BEFORE prompt rendering.

        This is the key fix for issue #595: Guards are evaluated after prompt
        rendering, causing template errors when referencing skipped actions.

        By evaluating guards FIRST with a rich context that includes upstream
        action data, we can skip actions early without attempting to render
        templates that would fail.

        Args:
            context: GuardEvaluationContext with all required data

        Returns:
            Tuple of (should_execute, skip_behavior):
            - (True, None) = guard passed, proceed with execution
            - (False, 'skip') = guard failed, skip with passthrough
            - (False, 'filter') = guard failed, filter out entirely
        """
        # Build rich context for guard evaluation using EvaluationContextProvider
        # This loads ALL upstream action data via historical node loader
        provider = EvaluationContextProvider()

        # Construct current_item if not provided
        if context.current_item is None:
            current_item = {
                "content": context.contents if isinstance(context.contents, dict) else {},
                "source_guid": (
                    context.contents.get("source_guid")
                    if isinstance(context.contents, dict)
                    else None
                ),
                "lineage": (
                    context.contents.get("lineage", [])
                    if isinstance(context.contents, dict)
                    else []
                ),
            }
        else:
            current_item = context.current_item

        try:
            config = ContextBuildConfig(
                agent_config=self.agent_config,
                agent_name=self.agent_name,
                agent_indices=self.agent_indices,
                dependency_configs=self.dependency_configs,
                file_path=context.file_path,
                source_content=context.source_content,
                loop_context=context.loop_context,
                workflow_metadata=context.workflow_metadata,
            )
            eval_context = provider.build_context(current_item=current_item, config=config)

            # Convert to flat dict for guard evaluation
            # This includes current content + upstream action data
            context_for_guard = eval_context.to_flat_dict()

            logger.debug(
                "Early guard evaluation for '%s' with context keys: %s",
                self.agent_name,
                list(context_for_guard.keys()),
            )

            # Evaluate guard with rich context
            should_execute, behavior = evaluate_guard_condition(
                self.agent_config, context_for_guard
            )

            if not should_execute:
                logger.debug(
                    "Early guard evaluation: '%s' will be skipped (behavior=%s)",
                    self.agent_name,
                    behavior,
                )

            return (should_execute, behavior)

        except (ValueError, KeyError, TypeError) as e:
            # On error, proceed with execution (don't skip)
            # The guard will be re-evaluated in run_dynamic_agent if needed
            logger.warning(
                "Early guard evaluation failed for '%s': %s. Proceeding with execution.",
                self.agent_name,
                e,
            )
            return (True, None)

    def supports_async(self) -> bool:
        """Return True as this generator supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    def create_agent_with_data(
        self,
        contents: Any,
        source_content: Optional[Any] = None,
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None,
    ) -> Tuple[List[Dict], bool, Dict]:
        """
        Create an agent with the provided data and generate results.

        Args:
            contents: Content to process
            source_content: Optional source content for prompt formatting
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references
            current_item: Optional current item dict containing lineage and
                source_guid for historical node loading
            file_path: Optional file path for constructing historical node paths

        Returns:
            Tuple containing:
            - generated data (List[Dict])
            - flag indicating if agent was executed (bool)
            - passthrough_fields extracted from field_context (Dict)

        Raises:
            RuntimeError: If agent creation or data generation fails
        """
        try:
            # CRITICAL FIX (Issue #595): Evaluate guards BEFORE prompt rendering
            # This prevents template errors when referencing fields from skipped actions.
            # If guard says skip/filter, return early without attempting prompt rendering.
            if self._has_guard_condition():
                guard_context = GuardEvaluationContext(
                    contents=contents,
                    current_item=current_item,
                    file_path=file_path,
                    source_content=source_content,
                    loop_context=loop_context,
                    workflow_metadata=workflow_metadata,
                )
                should_execute, behavior = self._evaluate_guard_early(guard_context)

                if not should_execute:
                    # Guard failed - return early without prompt rendering
                    if behavior == "filter":
                        # Filter behavior: return None to exclude item entirely
                        logger.debug(
                            "Guard filter: '%s' returning None (filtered out)", self.agent_name
                        )
                        return (None, False, {})
                    # Skip behavior: return original contents as passthrough
                    logger.debug(
                        "Guard skip: '%s' returning contents as passthrough", self.agent_name
                    )
                    return (contents, False, {})

            # Guard passed (or no guard) - proceed with prompt preparation
            # Resolve tools_path for dispatch_task() injection
            tools_path = resolve_tools_path(self.agent_config)

            # Prepare parameters for prompt preparation
            prep_params = {
                "agent_config": self.agent_config,
                "agent_name": self.agent_name,
                "contents": contents,
                "mode": "realtime",
                "agent_indices": self.agent_indices,
                "dependency_configs": self.dependency_configs,
                "source_content": source_content,
                "loop_context": loop_context,
                "workflow_metadata": workflow_metadata,
                "current_item": current_item,
                "file_path": file_path,
                "tools_path": tools_path,
            }
            prep_result = PromptPreparationService.prepare_prompt_with_context(**prep_params)

            # Execute agent with prepared prompt and context
            # Note: prep_result.formatted_prompt already includes few-shot samples
            # CRITICAL: Pass BOTH contexts to run_dynamic_agent:
            # - contents: Original data for guard evaluation and tools/UDFs (can access all fields)
            # - llm_context: Transformed data for LLM (has context_scope.drop applied)
            # Also pass skip_guard_eval=True since we already evaluated guards above
            tool_args = self.agent_config.get("tool_args", {})
            response, executed = run_dynamic_agent(
                self.agent_config,
                self.agent_name,
                contents,  # Original contents for guards/tools/UDFs
                prep_result.formatted_prompt,  # Already has few-shot samples and dispatch injected
                tools_path=tools_path,  # Use resolved tools_path
                tool_args=tool_args,
                source_content=source_content,
                llm_context=prep_result.llm_context,  # Transformed context for LLM
                skip_guard_eval=self._has_guard_condition(),  # Skip if already evaluated
            )

            return (response, executed, prep_result.passthrough_fields)
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            raise GenerationError(f"Failed to create agent with data: {str(e)}", cause=e) from e
