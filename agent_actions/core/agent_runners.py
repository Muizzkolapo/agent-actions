import os
import sys
import yaml
import shutil
from collections import OrderedDict
from agent_actions.logging_setup import logger
from agent_actions.core.utils import Utils
from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.handlers.file_handler import FileHandler
import json 
import logging

def copy_parent_output_to_child_staging(parent_output, child_base_dir):
    if parent_output and os.path.exists(parent_output):
        child_staging_dir = os.path.join(child_base_dir, 'staging')
        os.makedirs(child_staging_dir, exist_ok=True)
        for file in os.listdir(parent_output):
            shutil.copy(os.path.join(parent_output, file), child_staging_dir)
        logger.info(f"Copied parent output to child staging directory: {child_staging_dir}")

def copy_parent_source_to_child_source(parent_source, child_base_dir):
    if parent_source and os.path.exists(parent_source):
        child_source_dir = os.path.join(child_base_dir, 'source')
        os.makedirs(child_source_dir, exist_ok=True)
        for file in os.listdir(parent_source):
            shutil.copy(os.path.join(parent_source, file), child_source_dir)
        logger.info(f"Copied parent source to child source directory: {child_source_dir}")

def load_configs(constructor_path, default_path):
    with open(constructor_path, 'r', encoding='utf-8') as file:
        user_config = yaml.safe_load(file)

    with open(default_path, 'r', encoding='utf-8') as file:
        default_config = yaml.safe_load(file)

    return user_config, default_config

def validate_agent_name(agent_name, constructor_path):
    config_filename = os.path.splitext(os.path.basename(constructor_path))[0]
    if agent_name != config_filename:
        logger.error(f"Top-level key '{agent_name}' does not match the filename '{config_filename}'")
        raise ValueError(f"Top-level key '{agent_name}' does not match the filename '{config_filename}'")

def check_child_pipeline(user_config, agent_name):
    for item in user_config[agent_name]:
        if isinstance(item, dict) and 'child' in item:
            return item['child'][0]
    return None

def get_user_agents(user_config, agent_name):
    if 'agents' in user_config[agent_name]:
        return user_config[agent_name]['agents']
    else:
        return [agent for agent in user_config[agent_name] if isinstance(agent, dict) and 'agent_type' in agent]

def merge_agent_configs(user_agents, default_agent_config):
    agent_configs = {}
    for agent in user_agents:
        if 'agent_type' in agent:
            agent_type = agent['agent_type']
            default_agent = default_agent_config.copy()
            default_agent.update(agent)
            agent_configs[agent_type] = default_agent
    return agent_configs

def determine_execution_order(user_agents):
    dependency_graph = {agent['agent_type']: agent.get('dependencies', []) for agent in user_agents if 'agent_type' in agent}
    execution_order = Utils.topological_sort(dependency_graph)
    logger.info(f"Execution order determined: {execution_order}")
    return execution_order

def execute_parent_pipeline(parent_pipeline, constructor_path, user_code_path, default_path, use_tools):
    logger.info(f"Attempting to execute parent pipeline: {parent_pipeline}")
    parent_constructor_path = FileHandler.find_config_file(os.path.dirname(constructor_path), f"{parent_pipeline}.yml")
    if parent_constructor_path:
        logger.info(f"Parent pipeline config found at: {parent_constructor_path}")
        parent_output = run_agents(parent_constructor_path, user_code_path, default_path, use_tools)
        
        # Copy parent output to current pipeline's staging directory
        if parent_output:
            current_staging_dir = os.path.join(os.path.dirname(constructor_path), '..', 'agent_io', 'staging')
            os.makedirs(current_staging_dir, exist_ok=True)
            for file in os.listdir(parent_output):
                shutil.copy(os.path.join(parent_output, file), current_staging_dir)
            logger.info(f"Copied parent output to current staging directory: {current_staging_dir}")
    else:
        logger.error(f"Parent pipeline config not found for: {parent_pipeline}")

def process_final_output(ephemeral_directories, parent_output, constructor_path):
    if ephemeral_directories:
        final_output_folder = ephemeral_directories[-1]['output_folder']
        side_output_folder = os.path.join(os.path.dirname(final_output_folder), 'side_output')
        final_workflow_output = os.path.join(os.path.dirname(final_output_folder), 'final_workflow_output')

        # Ensure final_workflow_output directory exists
        os.makedirs(final_workflow_output, exist_ok=True)

        logger.debug(f"Final output folder: {final_output_folder}")
        logger.debug(f"Side output folder: {side_output_folder}")
        logger.debug(f"Final workflow output folder: {final_workflow_output}")

        if os.path.exists(side_output_folder):
            logger.debug("Side output folder exists. Merging with final output.")
            merge_json_files(side_output_folder, final_output_folder, final_workflow_output)
            logger.info("Side output combined with final output in final_workflow_output.")
        else:
            logger.debug("No side output folder. Copying last agent's output.")
            for file in os.listdir(final_output_folder):
                src = os.path.join(final_output_folder, file)
                dst = os.path.join(final_workflow_output, file)
                shutil.copy(src, dst)
                logger.debug(f"Copied: {src} -> {dst}")

            logger.info(f"Copied last agent's output to final_workflow_output: {final_workflow_output}")

        # Debug: List final contents of final_workflow_output
        logger.debug("Final contents of final_workflow_output:")
        for root, dirs, files in os.walk(final_workflow_output):
            for file in files:
                logger.debug(f"  - {os.path.join(root, file)}")

        # Log the contents of final_workflow_output
        logger.info(f"Contents of final_workflow_output ({final_workflow_output}):")
        for root, dirs, files in os.walk(final_workflow_output):
            for file in files:
                logger.info(f"  - {os.path.join(root, file)}")

        # Log information about copying final_workflow_output
        if parent_output:
            logger.info(f"Copying final_workflow_output to parent output: {parent_output}")
            for item in os.listdir(final_workflow_output):
                src = os.path.join(final_workflow_output, item)
                dst = os.path.join(parent_output, item)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    logger.info(f"  Copied file: {src} -> {dst}")
                elif os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    logger.info(f"  Copied directory: {src} -> {dst}")
        else:
            logger.info("No parent output specified. final_workflow_output will not be copied.")

        logger.info(f"Final workflow output is available at: {final_workflow_output}")
    else:
        logger.warning("No agents were executed. No final output generated.")
        final_workflow_output = None

    return final_workflow_output

def execute_child_pipeline(child_pipeline, constructor_path, user_code_path, default_path, use_tools, ephemeral_directories):
    if child_pipeline:
        logger.info(f"Attempting to execute child pipeline: {child_pipeline}")
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(constructor_path)))
        child_filename = f"{child_pipeline}.yml"
        logger.info(f"Searching for child pipeline config in base directory: {base_dir}")
        logger.info(f"Looking for file: {child_filename}")
        child_constructor_path = FileHandler.find_config_file(base_dir, child_filename)
        if child_constructor_path:
            logger.info(f"Child pipeline config found at: {child_constructor_path}")
            # Pass the final output folder and source folder of the parent pipeline to the child pipeline
            parent_final_output = ephemeral_directories[-1]['output_folder'] if ephemeral_directories else None
            parent_source = os.path.join(os.path.dirname(constructor_path), '..', 'agent_io', 'source')
            run_agents(child_constructor_path, user_code_path, default_path, use_tools, 
                       parent_output=parent_final_output, parent_source=parent_source)
        else:
            logger.error(f"Child pipeline config not found for: {child_pipeline}")
            logger.error(f"Searched in base directory: {base_dir}")
            logger.error(f"Searched for file: {child_filename}")
    else:
        logger.info("No child pipeline to execute.")

def run_agents(constructor_path, user_code_path, default_path, use_tools, parent_output=None, parent_source=None, parent_pipeline=None):
    """
    Run agents based on the provided constructor path and default path.
    """
    # Initialize variables
    current_agent_idx = 0
    previous_agent_type = None
    ephemeral_directories = []
    agent_name = None
    execution_order = []
    agent_configs = {}
    child_pipeline = None

    # If this is a child pipeline and we have parent output/source, copy them to the appropriate directories
    if parent_output or parent_source:
        child_base_dir = os.path.join(os.path.dirname(constructor_path), '..', 'agent_io')
        copy_parent_output_to_child_staging(parent_output, child_base_dir)
        copy_parent_source_to_child_source(parent_source, child_base_dir)

    if user_code_path and user_code_path not in sys.path:
        sys.path.insert(0, user_code_path)

    if not agent_name:
        user_config, default_config = load_configs(constructor_path, default_path)
        agent_name = ConfigValidator.find_agent_name(user_config)
        logger.info(f"Running agent workflow: {agent_name}")
        validate_agent_name(agent_name, constructor_path)
        child_pipeline = check_child_pipeline(user_config, agent_name)
        user_agents = get_user_agents(user_config, agent_name)
        default_agent_config = default_config['default_agent_config']
        agent_configs = merge_agent_configs(user_agents, default_agent_config)
        execution_order = determine_execution_order(user_agents)

    # Execute parent pipeline if present
    if parent_pipeline:
        execute_parent_pipeline(parent_pipeline, constructor_path, user_code_path, default_path, use_tools)

    for idx in range(current_agent_idx, len(execution_order)):
        agent_type = execution_order[idx]
        agent_config = agent_configs[agent_type]
        logger.info(f"Running agent {idx + 1}: {agent_config['agent_type']}")

        output_folder = run_agent(agent_config, agent_name, previous_agent_type, idx, len(execution_order), use_tools)
        previous_agent_type = agent_type

        directory_info = OrderedDict({
            'output_folder': output_folder,
            'ephemeral': agent_config.get('ephemeral', False)
        })
        ephemeral_directories.append(directory_info)

    # Process final output
    final_workflow_output = process_final_output(ephemeral_directories, parent_output, constructor_path)

    # Execute child pipeline if present
    execute_child_pipeline(child_pipeline, constructor_path, user_code_path, default_path, use_tools, ephemeral_directories)

    return final_workflow_output

def run_agent(agent_config, agent_name, previous_agent_type, idx, total_agents, use_tools):
    logger = logging.getLogger('agent_actions.core.agent_runners')
    try:
        # Show workflow name and total agents only at start
        if idx == 0:
            print(f"\n📋 Starting Workflow: {agent_name} ({total_agents} agents)")
            
        # Show current agent being executed with progress
        print(f"  ▶️  Running Agent [{idx + 1}/{total_agents}]: {agent_config['agent_type']}")
        
        loader = 'staging_loader' if idx == 0 else 'target_loader'
        function_name = 'generate_staging' if idx == 0 else 'generate_target'
        
        # Detailed info goes to log file only
        logger.debug(f"Processing agent {agent_config['agent_type']} in workflow {agent_name}")
        
        output_folder = AgentManager.process_and_generate_for_agent(
            agent_config, agent_name, previous_agent_type, loader, function_name)

        # Show agent completion
        print(f"  ✅ Completed Agent [{idx + 1}/{total_agents}]: {agent_config['agent_type']}")
        
        # Show workflow completion on last agent
        if idx == total_agents - 1:
            print(f"\n🎉 Workflow Complete: {agent_name}")
            print(f"   All {total_agents} agents completed successfully\n")
        
        return output_folder
    except Exception as e:
        print(f"  ❌ Failed Agent [{idx + 1}/{total_agents}]: {agent_config['agent_type']}")
        print(f"\n❌ Workflow Failed: {agent_name}")
        print(f"   Failed at agent {idx + 1} of {total_agents}\n")
        logger.error(f"Error in agent {agent_config['agent_type']}: {str(e)}")
        raise

def merge_json_files(input_dir, output_dir, combined_dir):
    # Create the combined folder if it doesn't exist
    if not os.path.exists(combined_dir):
        os.makedirs(combined_dir)
        logger.info(f"Created combined directory: {combined_dir}")

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
                    logger.error(f"Failed to decode JSON from {file1}")
        else:
            data1 = []

        # Read content of the second file (output)
        if os.path.exists(file2):
            with open(file2, 'r') as f2:
                try:
                    data2 = json.load(f2)
                except json.JSONDecodeError:
                    data2 = []
                    logger.error(f"Failed to decode JSON from {file2}")
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

        try:
            with open(output_path, 'w') as outfile:
                json.dump(merged_data, outfile, indent=4)
            logger.info(f"Merged {filename} has been written to {output_path}")
        except Exception as e:
            logger.error(f"Failed to write merged data to {output_path}: {e}")

def run_workflow(workflow_name, agents):
    try:
        for idx, agent in enumerate(agents):
            run_agent(agent, workflow_name, previous_agent_type, idx, use_tools)
        
        # Show workflow completion
        print(f"\n✨ Workflow Complete: {workflow_name}\n")
    except Exception as e:
        print(f"\n❌ Workflow Failed: {workflow_name}\n")
        raise
