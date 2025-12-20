"""Module for generating data using agents."""
from typing import Dict, Any, List, Optional, Tuple
from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.utilities.processor.processor_helpers import run_dynamic_agent
from agent_actions.configuration.interfaces import IGenerator, ProcessingMode
from agent_actions.orchestration.dependency_injection import registry

@registry.register_generator('data_generator')
class DataGenerator(IGenerator):
    """Handles agent creation and data generation (Single Responsibility)."""

    def __init__(
        self,
        agent_config: AgentEntryDict,
        agent_name: str,
        dependency_configs: Optional[Dict[str, AgentEntryDict]]=None,
        agent_indices: Optional[Dict[str, int]]=None
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
        source_content: Optional[Any]=None,
        loop_context: Optional[Dict]=None,
        workflow_metadata: Optional[Dict]=None,
        current_item: Optional[Dict]=None,
        file_path: Optional[str]=None
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
            # Prepare prompt using unified PromptPreparationService (Phase 2: Issue #487)
            # pylint: disable=import-outside-toplevel
            from agent_actions.prompt_generation.prompt_preparation_service import (
                PromptPreparationService
            )
            from agent_actions.utilities.tools_resolver import resolve_tools_path

            # Resolve tools_path for dispatch_task() injection
            tools_path = resolve_tools_path(self.agent_config)

            # Prepare parameters for prompt preparation
            prep_params = {
                'agent_config': self.agent_config,
                'agent_name': self.agent_name,
                'contents': contents,
                'mode': 'realtime',
                'agent_indices': self.agent_indices,
                'dependency_configs': self.dependency_configs,
                'source_content': source_content,
                'loop_context': loop_context,
                'workflow_metadata': workflow_metadata,
                'current_item': current_item,
                'file_path': file_path,
                'tools_path': tools_path
            }
            prep_result = PromptPreparationService.prepare_prompt_with_context(
                **prep_params
            )

            # Execute agent with prepared prompt and context
            # Note: prep_result.formatted_prompt already includes few-shot samples
            # CRITICAL: Pass BOTH contexts to run_dynamic_agent:
            # - contents: Original data for guard evaluation and tools/UDFs (can access all fields)
            # - llm_context: Transformed data for LLM (has context_scope.drop applied)
            tool_args = self.agent_config.get('tool_args', {})
            response, executed = run_dynamic_agent(
                self.agent_config,
                self.agent_name,
                contents,  # Original contents for guards/tools/UDFs
                prep_result.formatted_prompt,  # Already has few-shot samples and dispatch injected
                tools_path=tools_path,  # Use resolved tools_path
                tool_args=tool_args,
                source_content=source_content,
                llm_context=prep_result.llm_context  # Transformed context for LLM
            )

            return (response, executed, prep_result.passthrough_fields)
        except Exception as e:
            # pylint: disable=import-outside-toplevel
            from agent_actions.errors import GenerationError  # New modular pattern!
            raise GenerationError(
                f'Failed to create agent with data: {str(e)}', cause=e
            ) from e
