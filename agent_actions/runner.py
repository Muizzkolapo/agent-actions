"""
Module for running agents based on a specified agent configuration.
"""

import argparse
import logging
import os
import sys
import traceback
from collections import deque, OrderedDict
import shutil
import yaml

try:
    from agent_actions.agent_utils.processor.clean_target import clean_agent_output
    from agent_actions.agent_utils.processor.process_target import process_and_generate_for_agent
    from agent_actions.agent_utils.processor.process_target import find_config_file
    from agent_actions.agent_utils.transformers.tooling import execute_user_defined_function
    from agent_actions.agent_utils.transformers.validator import validate_agent_config
except ImportError:
    clean_agent_output = None
    process_and_generate_for_agent = None
    find_config_file = None
    execute_user_defined_function = None
    validate_agent_config = None


def find_agents_name(config):
    """
    Find the name of the agent from the configuration.
    """
    return next(iter(config))


def topological_sort(dependencies):
    """
    Perform a topological sort on the dependencies graph.
    """
    in_degree = {u: 0 for u in dependencies}
    for u in dependencies:
        for v in dependencies[u]:
            in_degree[v] += 1

    queue = deque([u for u in in_degree if in_degree[u] == 0])
    ordered = []

    while queue:
        vertex = queue.popleft()
        ordered.append(vertex)
        for neighbor in dependencies[vertex]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(ordered) != len(dependencies):
        raise ValueError("There is a cycle in the dependencies")

    return ordered[::-1]

def run_agent(agent_config, agent_name, previous_agent_type, idx, use_tools):
    """
    Run an agent based on the provided configuration.
    """
    try:
        loader = 'staging_loader' if idx == 0 else 'target_loader'
        function_name = 'generate_staging' if idx == 0 else 'generate_target'
        output_folder = process_and_generate_for_agent(agent_config, agent_name, previous_agent_type, loader, function_name)

        if use_tools:
            function_name = 'extract_all_lists' if idx == 0 else 'flatten_nested_dictionaries'
            clean_agent_output(agent_name, agent_config['agent_type'], function_name)

        if 'udf' in agent_config:
            udf = agent_config['udf']
            print(f"Calling UDF: {udf}")
            result = execute_user_defined_function(udf)
            print(f"UDF result: {result}")

    except Exception as e:
        logging.error("Error running agent %s: %s", agent_config['agent_type'], e)
        print(f"Error running agent {agent_config['agent_type']}: {e}")
        raise

    return output_folder


def run_agents(constructor_path, user_code_path, default_path, use_tools):
    """
    Run agents based on the provided constructor path and default path.
    """
    if user_code_path and user_code_path not in sys.path:
        sys.path.insert(0, user_code_path)

    with open(constructor_path, 'r', encoding='utf-8') as file:
        user_config = yaml.safe_load(file)

    with open(default_path, 'r', encoding='utf-8') as file:
        default_config = yaml.safe_load(file)

    agent_name = find_agents_name(user_config)

    # Check if the configuration file's top-level key matches the expected agent name
    config_filename = os.path.splitext(os.path.basename(constructor_path))[0]
    if agent_name != config_filename:
        raise ValueError(f"Top-level key '{agent_name}' does not match the filename '{config_filename}'")

    user_agents = [agent for agent in user_config[agent_name] if isinstance(agent, dict) and 'agent_type' in agent]
    default_agent_config = default_config['default_agent_config']

    agent_configs = {}
    for agent in user_agents:
        if 'agent_type' in agent:
            agent_type = agent['agent_type']
            default_agent = default_agent_config.copy()
            default_agent.update(agent)
            agent_configs[agent_type] = default_agent

    for agent_config in agent_configs.values():
        pass  # validate_agent_config(agent_config)

    dependency_graph = {agent['agent_type']: agent.get('dependencies', []) for agent in user_agents if 'agent_type' in agent}
    execution_order = topological_sort(dependency_graph)

    # Correctly locate and execute the top-level UDF
    top_level_udf = next((item['udf'] for item in user_config[agent_name] if 'udf' in item), None)
    if top_level_udf:
        print(f"Executing top-level UDF: {top_level_udf}")
        result = execute_user_defined_function(top_level_udf)
        if result is None:
            print(f"Failed to execute top-level UDF: {top_level_udf}. Exiting.")
            sys.exit(1)
        print(f"Top-level UDF result: {result}")

    previous_agent_type = None
    ephemeral_directories = []

    for idx, agent_type in enumerate(execution_order):
        agent_config = agent_configs[agent_type]
        print(f"  Agent {idx + 1}: {agent_config['agent_type']}")
        output_folder = run_agent(agent_config, agent_name, previous_agent_type, idx, use_tools)
        previous_agent_type = agent_type

        directory_info = OrderedDict({
            'output_folder': output_folder,
            'ephemeral': agent_config.get('ephemeral', False)
        })

        ephemeral_directories.append(directory_info)

    end_workflow_udf = next((agent['end_of_workflow'] for agent in user_agents if 'end_of_workflow' in agent), None)
    if end_workflow_udf:
        print(f"Executing end-of-workflow UDF: {end_workflow_udf}")
        result = execute_user_defined_function(end_workflow_udf)
        if result is None:
            print(f"Failed to execute end-of-workflow UDF: {end_workflow_udf}. Exiting.")
            sys.exit(1)
        print(f"End-of-workflow UDF result: {result}")
    
    directories_cleaned = False
    for i, directory in enumerate(ephemeral_directories):
        if directory['ephemeral'] and i != len(ephemeral_directories) - 1:
            folder_path = directory['output_folder']
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
                directories_cleaned = True

    if directories_cleaned:
        print("Finished cleaning up ephemeral directories.")




def get_all_agent_paths(base_dir):
    """
    Get a list of all agent configuration file paths within the base directory.
    """
    agent_paths = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".yml"):
                agent_paths.append(os.path.join(root, file))
    return agent_paths


def check_agent_name_unique(agent_name, base_dir):
    """
    Check if the agent name is unique across the entire project.
    """
    all_agent_paths = get_all_agent_paths(base_dir)
    agent_names = [os.path.splitext(os.path.basename(path))[0] for path in all_agent_paths]
    return agent_names.count(agent_name) == 1


def check_agent_file_unique(full_path, base_dir):
    """
    Check if the agent configuration file path is unique across the entire project.
    """
    all_agent_paths = get_all_agent_paths(base_dir)
    return all_agent_paths.count(full_path) == 1


def main():
    """
    Main function to parse command-line arguments and run agents.
    """
    parser = argparse.ArgumentParser(description="Run agents with a specified agent configuration.")
    parser.add_argument("-a", "--agent", required=True, help="Name of the schema (agent configuration file without path)")
    parser.add_argument("-u", "--user_code", help="Path to the user's code folder containing UDFs")
    args = parser.parse_args()

    current_dir = os.getcwd()
    agent_config_dir = os.path.join(current_dir, 'agent_config')
    schema_dir = os.path.join(current_dir, 'schema')
    io_dir = os.path.join(current_dir, 'agent_io')
    filename = args.agent

    default_config_path = os.path.join(current_dir, 'agent_actions.yml')

    required_dirs = [agent_config_dir, schema_dir, io_dir]
    for required_dir in required_dirs:
        if not os.path.exists(required_dir):
            print(f"Error: The directory '{required_dir}' does not exist.")
            sys.exit(1)

    if not filename.endswith(".yml"):
        filename += ".yml"
    full_path = find_config_file(agent_config_dir, filename)

    if full_path is None:
        print(f"Error: The configuration file '{filename}' does not exist in '{agent_config_dir}'.")
        sys.exit(1)

    if not os.path.exists(default_config_path):
        print(f"Error: The default configuration file does not exist in '{current_dir}'.")
        sys.exit(1)

    project_dir = os.path.abspath(os.path.join(current_dir))
    if not check_agent_file_unique(full_path, project_dir):
        print(f"Error: '{full_path}' is not unique across the entire project.")
        sys.exit(1)

    agent_name = os.path.splitext(filename)[0]
    if not check_agent_name_unique(agent_name, project_dir):
        print(f"Error: The agent name '{agent_name}' is not unique across the entire project.")
        sys.exit(1)

    # Load the agent configuration file
    with open(full_path, 'r') as config_file:
        config_data = yaml.safe_load(config_file)
    
    # Extract the agent configurations
    if agent_name not in config_data:
        print(f"Error: The top-level key '{agent_name}' is not found in the configuration file.")
        sys.exit(1)

    agent_config = config_data[agent_name]

    # Separate UDF entries from agent configurations
    udf_entries = [entry for entry in agent_config if 'udf' in entry]
    agent_entries = [entry for entry in agent_config if 'agent_type' in entry]

    # Print a summary of the loaded agent configuration
    print(f"Loaded configuration for '{agent_name}' with {len(agent_entries)} agents.")
    for idx, agent in enumerate(agent_entries):
        if 'agent_type' in agent:
            print(f"  Agent {idx + 1}: {agent['agent_type']}")

    # Validate that agent_config is a list
    if not isinstance(agent_config, list):
        print(f"Error: The configuration for '{filename}' is not a list.")
        sys.exit(1)

    # Validate the agent configuration
    is_valid, message = validate_agent_config(agent_entries)
    if not is_valid:
        print(f"Error: {message}")
        sys.exit(1)

    # Check for user_code path if UDFs are defined
    if udf_entries and not args.user_code:
        print(f"Error: UDFs are defined in the configuration but no user code path is provided with the '-u' option.")
        sys.exit(1)

    use_tools = args.user_code is not None

    try:
        run_agents(full_path, args.user_code, default_config_path, use_tools)
    except ValueError as ve:
        print(f"Configuration error: {ve}. Please make sure the top-level key in the YAML file matches the filename.")
        sys.exit(1)
    except FileNotFoundError as fe:
        print(f"File not found: {fe}")
        sys.exit(1)
    except yaml.YAMLError as ye:
        print(f"YAML parsing error: {ye}")
        sys.exit(1)

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
