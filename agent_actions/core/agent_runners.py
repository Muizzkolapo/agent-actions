import os
import sys
import yaml
import shutil
from collections import deque, OrderedDict
from agent_actions.core.agent_handlers import clean_agent_output, process_and_generate_for_agent
from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.logging_setup import logger
from agent_actions.core.state_management import save_checkpoint, load_checkpoint, remove_checkpoint
from agent_actions.core.utils import topological_sort
from agent_actions.core.agent_handlers import find_agents_name

import json 

def run_agent(agent_config, agent_name, previous_agent_type, idx, use_tools):
    logger.info(f"Running agent: {agent_config['agent_type']}")

    try:
        loader = 'staging_loader' if idx == 0 else 'target_loader'
        function_name = 'generate_staging' if idx == 0 else 'generate_target'
        output_folder = process_and_generate_for_agent(agent_config, agent_name, previous_agent_type, loader, function_name)

        if use_tools:
            if agent_config['model_vendor'].lower() == 'tool' and agent_config.get('side_output', False):
                # Handle side output for tools
                side_output_folder = os.path.join(output_folder, 'side_output')
                if os.path.exists(side_output_folder):
                    logger.info(f"Side output generated for {agent_config['agent_type']}")
            else:
                function_name = 'extract_all_lists' if idx == 0 else 'flatten_nested_dictionaries'
                clean_agent_output(agent_name, agent_config['agent_type'], function_name)

    except Exception as e:
        logger.error("Error running agent %s: %s", agent_config['agent_type'], e, exc_info=True)
        raise

    return output_folder



def run_agents(constructor_path, user_code_path, default_path, use_tools):
    """
    Run agents based on the provided constructor path and default path.
    Implements state management and checkpointing.
    """
    logger.info(f"Running agents with constructor path: {constructor_path}, user code path: {user_code_path}, default path: {default_path}")

    # Load checkpoint if available
    state = load_checkpoint()
    if not state:
        state = {
            'current_agent_idx': 0,
            'previous_agent_type': None,
            'ephemeral_directories': [],
            'constructor_path': constructor_path,
            'user_code_path': user_code_path,
            'default_path': default_path,
            'agent_name': None,
            'execution_order': [],
            'agent_configs': {},
        }

    if user_code_path and user_code_path not in sys.path:
        sys.path.insert(0, user_code_path)

    if not state['agent_name']:
        with open(constructor_path, 'r', encoding='utf-8') as file:
            user_config = yaml.safe_load(file)

        with open(default_path, 'r', encoding='utf-8') as file:
            default_config = yaml.safe_load(file)

        state['agent_name'] = find_agents_name(user_config)
        logger.info(f"Determined agent name: {state['agent_name']}")

        config_filename = os.path.splitext(os.path.basename(constructor_path))[0]
        if state['agent_name'] != config_filename:
            logger.error(f"Top-level key '{state['agent_name']}' does not match the filename '{config_filename}'")
            raise ValueError(f"Top-level key '{state['agent_name']}' does not match the filename '{config_filename}'")

        user_agents = [agent for agent in user_config[state['agent_name']] if isinstance(agent, dict) and 'agent_type' in agent]
        default_agent_config = default_config['default_agent_config']

        for agent in user_agents:
            if 'agent_type' in agent:
                agent_type = agent['agent_type']
                default_agent = default_agent_config.copy()
                default_agent.update(agent)
                state['agent_configs'][agent_type] = default_agent

        dependency_graph = {agent['agent_type']: agent.get('dependencies', []) for agent in user_agents if 'agent_type' in agent}
        state['execution_order'] = topological_sort(dependency_graph)
        logger.info(f"Execution order determined: {state['execution_order']}")

    previous_agent_type = state['previous_agent_type']
    for idx in range(state['current_agent_idx'], len(state['execution_order'])):
        agent_type = state['execution_order'][idx]
        agent_config = state['agent_configs'][agent_type]
        logger.info(f"Running agent {idx + 1}: {agent_config['agent_type']}")

        output_folder = run_agent(agent_config, state['agent_name'], previous_agent_type, idx, use_tools)
        previous_agent_type = agent_type
        state['previous_agent_type'] = previous_agent_type

        directory_info = OrderedDict({
            'output_folder': output_folder,
            'ephemeral': agent_config.get('ephemeral', False)
        })
        state['ephemeral_directories'].append(directory_info)
        
        # Update the current agent index in the state
        state['current_agent_idx'] = idx + 1
        save_checkpoint(state)

    # Combine side output with final output
    final_output_folder = state['ephemeral_directories'][-1]['output_folder']
    side_output_folder = os.path.join(os.path.dirname(final_output_folder), 'side_output')
    final_workflow_output = os.path.join(os.path.dirname(final_output_folder), 'final_workflow_output')

    if os.path.exists(side_output_folder):
        merge_json_files(side_output_folder, final_output_folder, final_workflow_output)
        logger.info("Side output combined with final output successfully.")
        logger.info("Side output folder preserved for future reference.")
    else:
        logger.info("No side output folder found. Skipping combination.")

    # Remove the checkpoint file
    remove_checkpoint()

    return final_workflow_output


def merge_json_files(input_dir, output_dir, combined_dir):
    # Create the combined folder if it doesn't exist
    if not os.path.exists(combined_dir):
        os.makedirs(combined_dir)

    # Get list of all files in the input directory
    input_files = [f for f in os.listdir(input_dir) if f.endswith('.json')]

    # Iterate through the files in input folder
    for filename in input_files:
        # Paths for both the input and output folders
        file1 = os.path.join(input_dir, filename)
        file2 = os.path.join(output_dir, filename)

        # Read content of the first file (input)
        if os.path.exists(file1):
            with open(file1, 'r') as f1:
                try:
                    data1 = json.load(f1)
                except json.JSONDecodeError:
                    data1 = []
        else:
            data1 = []

        # Read content of the second file (output)
        if os.path.exists(file2):
            with open(file2, 'r') as f2:
                try:
                    data2 = json.load(f2)
                except json.JSONDecodeError:
                    data2 = []
        else:
            data2 = []

        # Merge both data
        merged_data = data1 + data2

        # Clean up the merged data by removing the 'side_output' key
        for item in merged_data:
            if 'content' in item and 'side_output' in item['content']:
                del item['content']['side_output']

        # Write the merged content into the combined folder
        output_path = os.path.join(combined_dir, filename)

        with open(output_path, 'w') as outfile:
            json.dump(merged_data, outfile, indent=4)

        print(f"Merged {filename} has been written to {output_path}")