"""
This module contains a function to clean agent output by applying a specified
function to each JSON file in the target directory of the agent.
"""

import os
import json

def clean_agent_output(agent_name, agent_type, function_name):
    """
    Cleans the agent output by applying a specified function to each JSON file
    in the target directory of the agent.

    :param agent_name: Name of the agent
    :param agent_type: Type of the agent
    :param function_name: Name of the function to apply to the JSON data
    """
    project_root = os.getcwd()  # Get current working directory
    input_directory = os.path.join(project_root, 'agent_io', agent_name, 'target', agent_type)
    function_call = globals().get(function_name)
    if function_call and callable(function_call):
        for root, _, files in os.walk(input_directory):
            for file_name in files:
                if file_name.endswith('.json'):
                    file_path = os.path.join(root, file_name)
                    with open(file_path, 'r', encoding='utf-8') as file:
                        data = json.load(file)
                    flattened_data = function_call(data)
                    with open(file_path, 'w', encoding='utf-8') as file:
                        json.dump(flattened_data, file, indent=4)
