import json
import os
import shutil
from typing import Callable, Optional, Dict, Any
from agent_actions.handlers.file_handler import FileHandler


class AgentManager:
    """
    A class for managing agent directories and configurations.
    """
    
    @staticmethod
    def clean_agent_directories(agent_name: str) -> bool:
        """
        Deletes all files under the source and target folders for the specified agent.
        
        Args:
            agent_name: Name of the agent whose directories should be cleaned
            
        Returns:
            bool: True if directories were successfully cleaned, False otherwise
        """
        current_dir = os.getcwd()
        agent_folder = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')
        
        if agent_folder is None:
            print(f"Agent folder not found for agent: {agent_name}")
            return False
        
        source_dir = os.path.join(agent_folder, 'source')
        target_dir = os.path.join(agent_folder, 'target')
        
        for directory in [source_dir, target_dir]:
            if os.path.exists(directory):
                shutil.rmtree(directory)
                print(f"Deleted directory: {directory}")
            else:
                print(f"Directory not found: {directory}")
                
        return True
    
    @staticmethod
    def clean_agent_output(agent_name: str, agent_type: str, function_name: str) -> int:
        """
        Cleans the agent output by applying a specified function to each JSON file
        in the target directory of the agent.
        
        Args:
            agent_name: Name of the agent
            agent_type: Type of the agent
            function_name: Name of the function to apply to the JSON data
            
        Returns:
            int: Number of files successfully processed
        """
        project_root = os.getcwd()
        input_directory = os.path.join(project_root, 'agent_io', agent_name, 'target', agent_type)
        
        # Get the function from globals
        function_call: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = globals().get(function_name)
        
        processed_count = 0
        if function_call and callable(function_call):
            for root, _, files in os.walk(input_directory):
                for file_name in files:
                    if file_name.endswith('.json'):
                        file_path = os.path.join(root, file_name)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as file:
                                data = json.load(file)
                                
                            processed_data = function_call(data)
                            
                            with open(file_path, 'w', encoding='utf-8') as file:
                                json.dump(processed_data, file, indent=4)
                            
                            processed_count += 1
                        except (json.JSONDecodeError, IOError) as e:
                            print(f"Error processing file {file_path}: {str(e)}")
        
        return processed_count