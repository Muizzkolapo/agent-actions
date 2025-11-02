"""Module for generating data using agents."""
from typing import Dict, Any, List, Optional, Tuple
from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.utilities.utils_processor_helpers import run_dynamic_agent
from agent_actions.configuration.interfaces import IGenerator, ProcessingMode
from agent_actions.orchestration.dependency_injection import registry

@registry.register_generator('data_generator')
class DataGenerator(IGenerator):
    """Handles agent creation and data generation (Single Responsibility)."""

    def __init__(self, agent_config: AgentEntryDict, agent_name: str):
        """
        Initialize the data generator.
        
        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name

    def supports_async(self) -> bool:
        """Return True as this generator supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def create_agent_with_data(self, contents: Any, source_content: Optional[Any]=None) -> Tuple[List[Dict], bool]:
        """
        Create an agent with the provided data and generate results.

        Args:
            contents: Content to process
            source_content: Optional source content for prompt formatting

        Returns:
            Tuple containing the generated data and a flag indicating if the
            agent was executed

        Raises:
            RuntimeError: If agent creation or data generation fails
        """
        try:
            # Prepare prompt using unified PromptPreparationService (Phase 2: Issue #487)
            from agent_actions.prompt_generation.prompt_preparation_service import PromptPreparationService

            prep_result = PromptPreparationService.prepare_prompt_with_context(
                agent_config=self.agent_config,
                agent_name=self.agent_name,
                contents=contents if isinstance(contents, dict) else {},
                mode='realtime',
                source_content=source_content
            )

            # Check if model vendor is configured
            tool_args = self.agent_config.get('tool_args', {})
            if not self.agent_config.get('model_vendor'):
                return ([{'content': contents}], False)

            # Execute agent with prepared prompt and context
            # Note: prep_result.formatted_prompt already includes few-shot samples
            # CRITICAL: Pass BOTH contexts to run_dynamic_agent:
            # - contents: Original data for guard evaluation and tools/UDFs (can access all fields)
            # - llm_context: Transformed data for LLM (has context_scope.drop applied)
            response, executed = run_dynamic_agent(
                self.agent_config,
                self.agent_name,
                contents if isinstance(contents, dict) else {},  # Original contents for guards/tools/UDFs
                prep_result.formatted_prompt,  # Already has few-shot samples
                tools_path=self.agent_config.get('tools', {}).get('path'),
                tool_args=tool_args,
                source_content=source_content,
                llm_context=prep_result.llm_context  # Transformed context for LLM
            )
            return (response, executed)
        except Exception as e:
            from agent_actions.shared.exceptions import GenerationError
            raise GenerationError(f'Failed to create agent with data: {str(e)}', cause=e)