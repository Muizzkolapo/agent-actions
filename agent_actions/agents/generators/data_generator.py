"""Module for generating data using agents."""
from typing import Dict, Any, List, Optional, Tuple
from agent_actions.core.parser.config_types import AgentEntryDict

from agent_actions.agents.base import agent_builder
from agent_actions.agents.handlers.prompt_handler import PromptLoader
from agent_actions.agents.transformers.prompt_utils import PromptUtils
from agent_actions.core.constants import PROMPT_KEY
from agent_actions.agents.transformers.sample_enricher import SampleEnricher
from agent_actions.agents.transformers.data_transformer import DataTransformer
from agent_actions.core.utils.processor_helpers import apply_remove_collection, run_dynamic_agent

from agent_actions.core.contracts.interfaces import IGenerator, ProcessingMode
from ...core.graph.dependency_injection import registry


@registry.register_generator("data_generator")
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

    def create_agent_with_data(
        self,
        contents: Any,
        source_content: Optional[Any] = None,
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None
    ) -> Tuple[List[Dict], bool]:
        """
        Create an agent with the provided data and generate results.
        
        Args:
            contents: Content to process
            source_content: Optional source content for prompt formatting
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references

        Returns:
            Tuple containing the generated data and a flag indicating if the
            agent was executed
            
        Raises:
            RuntimeError: If agent creation or data generation fails
        """
        try:
            # Format prompt with content
            formatted_prompt, contents = self._format_prompt(
                contents, source_content, loop_context, workflow_metadata
            )
            
            # Append few-shot samples if configured
            formatted_prompt = SampleEnricher.append_few_shot_samples(
                formatted_prompt, self.agent_config, self.agent_name
            )
            
            tool_args = self.agent_config.get('tool_args', {})

            # Create and run the agent through the shared utility
            response, executed = run_dynamic_agent(
                self.agent_config,
                self.agent_name,
                contents,
                formatted_prompt,
                tools_path=self.agent_config.get('tools', {}).get('path'),
                tool_args=tool_args,
                source_content=source_content,
            )
            return response, executed
        except Exception as e:
            from agent_actions.core.exceptions import GenerationError
            raise GenerationError(f"Failed to create agent with data: {str(e)}", cause=e)

    def _apply_remove_collection(self, contents: Dict) -> Dict:
        """
        Apply remove_collection transformation to contents.
        
        Args:
            contents: Content to transform
            
        Returns:
            Transformed content
        """
        return apply_remove_collection(contents, self.agent_config)

    def _format_prompt(
        self,
        contents: Dict,
        source_content: Optional[Any] = None,
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None
    ) -> Tuple[str, Dict]:
        """
        Format the prompt with contents and source content.

        Args:
            contents: Content for prompt formatting
            source_content: Optional source content for prompt formatting
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references

        Returns:
            Tuple of the formatted prompt and cleaned content
        """
        # Get raw prompt
        raw_prompt = self.agent_config.get(PROMPT_KEY, '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            raw_prompt = "Process the following content: {content}"

        # Build field context for {reference.field} pattern
        field_context = {}
        if source_content:
            field_context['source'] = source_content

        # Add dependency outputs from contents
        # Contents may contain dependency data
        if isinstance(contents, dict):
            field_context.update(contents)

        # Add special loop context for {loop.*} references
        if loop_context:
            field_context['loop'] = loop_context

        # Add workflow metadata for {workflow.*} references
        if workflow_metadata:
            field_context['workflow'] = workflow_metadata

        # Replace patterns in order
        source_loaded_prompt = PromptUtils.replace_source_context_placeholder(
            raw_prompt,
            source_content
        )

        # NEW: Replace field references
        if field_context:
            source_loaded_prompt = PromptUtils.replace_field_references(
                source_loaded_prompt,
                field_context
            )

        prompt, cleaned_contents = PromptUtils.replace_placeholders(source_loaded_prompt, contents)
        return prompt, cleaned_contents