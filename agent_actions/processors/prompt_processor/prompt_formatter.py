"""Module for prompt formatting and loading."""
import json
import os
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.processors.prompt_processor.prompt_utils import PromptUtils


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
            raw_prompt = agent_config.get('prompt', '')
            if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
                raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
            if not raw_prompt:
                raw_prompt = "Process the following content: {content}"
            return raw_prompt
        except Exception as e:
            raise ValueError(f"Failed to get raw prompt: {str(e)}")
    
    @staticmethod
    def format_prompt(raw_prompt, source_content, context_data):
        """
        Replace placeholders in the raw prompt with source content and input documentation.
        
        Parameters:
            raw_prompt: Template prompt with placeholders
            source_content: Content to replace source placeholders
            context_data: Content to replace context placeholders
            
        Returns:
            Formatted prompt with all placeholders replaced
            
        Raises:
            ValueError: If prompt formatting fails
        """
        try:
            source_loaded_prompt = PromptUtils.replace_guid_placeholder(raw_prompt, str(source_content))
            formatted_prompt = PromptUtils.replace_placeholders(source_loaded_prompt, context_data)
            return formatted_prompt
        except Exception as e:
            raise ValueError(f"Failed to format prompt: {str(e)}")
    