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
    
    @staticmethod
    def load_source_content(source_path, context_data):
        """
        Load source content based on the input documentation's GUID.
        If the source file doesn't exist, create it with an empty structure.
        
        Parameters:
            source_path: Path to the source file
            context_data: Context data containing GUID
            
        Returns:
            Loaded source content or empty structure if newly created
            
        Raises:
            IOError: If source content loading or creation fails
        """
        try:
            if not source_path:
                return None
                
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            
            # Create empty source file if it doesn't exist
            if not os.path.exists(source_path):
                empty_source = []
                with open(source_path, 'w') as file:
                    json.dump(empty_source, file, indent=2)
                return None
                
            with open(source_path, 'r') as file:
                source_data = json.load(file)
                if isinstance(context_data, dict) and "guid" in context_data:
                    guid = context_data["guid"]
                    for item in source_data:
                        if guid in item:
                            return item[guid]
            return None
        except Exception as e:
            raise IOError(f"Failed to load or create source content: {str(e)}")