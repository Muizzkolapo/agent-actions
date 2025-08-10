"""Module for prompt formatting and loading."""
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.constants import PROMPT_KEY
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
            raw_prompt = agent_config.get(PROMPT_KEY, '')
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
            source_content: Content to replace source placeholders (from source file)
            context_data: Content to replace context placeholders (current context)
            
        Returns:
            Formatted prompt with all placeholders replaced
            
        Raises:
            ValueError: If prompt formatting fails
        """
        try:
            # Use new method that supports field selection
            source_loaded_prompt = PromptUtils.replace_source_context_placeholder(
                raw_prompt, 
                source_content
            )
            formatted_prompt, _ = PromptUtils.replace_placeholders(source_loaded_prompt, context_data)
            return formatted_prompt
        except Exception as e:
            raise ValueError(f"Failed to format prompt: {str(e)}")
    