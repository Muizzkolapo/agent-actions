"""Module for generating data using agents."""
from typing import Dict, Any, List, Optional

from agent_actions.models import agent_builder
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.processors.prompt_processor.prompt_utils import PromptUtils
from agent_actions.constants import PROMPT_KEY
from agent_actions.transformers.data_transformer import DataTransformer

from .interfaces import IDataGenerator


class DataGenerator(IDataGenerator):
    """Handles agent creation and data generation (Single Responsibility)."""

    def __init__(self, agent_config: Dict, agent_name: str):
        """
        Initialize the data generator.
        
        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name

    def create_agent_with_data(
        self, 
        contents: Any, 
        source_content: Optional[Any] = None
    ) -> List[Dict]:
        """
        Create an agent with the provided data and generate results.
        
        Args:
            contents: Content to process
            source_content: Optional source content for prompt formatting
            
        Returns:
            Generated data from the agent
            
        Raises:
            RuntimeError: If agent creation or data generation fails
        """
        try:

            # Apply remove_collection before creating the agent
            contents = self._apply_remove_collection(contents)
            
            # Format prompt with content
            formatted_prompt, contents = self._format_prompt(contents, source_content)
            tool_args = self.agent_config.get('tool_args', {})

            # Create and run the agent
            return agent_builder.create_dynamic_agent(
                self.agent_config,
                self.agent_name,
                contents,
                source_content=source_content,  # Pass source_content explicitly
                tool_args=tool_args,
                formatted_prompt=formatted_prompt,
                tools_path=self.agent_config.get('tools', {}).get('path')
            )
        except Exception as e:
            raise RuntimeError(f"Failed to create agent with data: {str(e)}")

    def _apply_remove_collection(self, contents: Dict) -> Dict:
        """
        Apply remove_collection transformation to contents.
        
        Args:
            contents: Content to transform
            
        Returns:
            Transformed content
        """
        remove_collection = self.agent_config.get('remove_collection', [])
        if remove_collection:
            return DataTransformer.remove_schema_objects(contents, remove_collection)
        return contents

    def _format_prompt(self, contents: Dict, source_content: Optional[Any] = None) -> str:
        """
        Format the prompt with contents and source content.
        
        Args:
            contents: Content for prompt formatting
            source_content: Optional source content for prompt formatting
            
        Returns:
            Formatted prompt
        """
        # Get raw prompt
        raw_prompt = self.agent_config.get(PROMPT_KEY, '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            raw_prompt = "Process the following content: {content}"

        source_loaded_prompt = PromptUtils.replace_guid_placeholder(
            raw_prompt,
            str(source_content)
        )
        prompt, cleaned_contents = PromptUtils.replace_placeholders(source_loaded_prompt, contents)
        return prompt, cleaned_contents