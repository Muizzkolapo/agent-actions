import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ToolProcessor:
    @staticmethod
    def process_tool(agent_config: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process data using a tool function
        
        Args:
            agent_config: The tool agent configuration
            input_data: The input data to process
            
        Returns:
            Dict containing the processed data
        """
        try:
            tool_function = agent_config.get('function_name')
            if not tool_function:
                raise ValueError("Tool agent must specify 'function_name'")
                
            # Import the tool function
            module_path, function_name = tool_function.rsplit('.', 1)
            module = importlib.import_module(module_path)
            function = getattr(module, function_name)
            
            # Process the data
            result = function(input_data)
            
            # Ensure we got a valid result
            if result is None:
                raise ValueError(f"Tool function {tool_function} returned None")
                
            return result
            
        except Exception as e:
            logger.error(f"Error processing tool {agent_config.get('agent_type')}: {str(e)}")
            raise