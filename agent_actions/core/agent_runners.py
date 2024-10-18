import os
import sys
import yaml
import shutil
from collections import deque, OrderedDict
from agent_actions.core.agent_handlers import clean_agent_output, process_and_generate_for_agent
from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.logging_setup import logger
from agent_actions.core.state_management import save_checkpoint, load_checkpoint, remove_checkpoint
from agent_actions.core.utils import Utils
from agent_actions.core.agent_handlers import find_agents_name,find_config_file
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





def run_agents(constructor_path, user_code_path, default_path, use_tools, parent_output=None, parent_source=None, parent_pipeline=None):
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
            'child_pipeline': None,
        }

    # If this is a child pipeline and we have parent output/source, copy them to the appropriate directories
    if parent_output or parent_source:
        child_base_dir = os.path.join(os.path.dirname(constructor_path), '..', 'agent_io')
        
        if parent_output and os.path.exists(parent_output):
            child_staging_dir = os.path.join(child_base_dir, 'staging')
            os.makedirs(child_staging_dir, exist_ok=True)
            for file in os.listdir(parent_output):
                shutil.copy(os.path.join(parent_output, file), child_staging_dir)
            logger.info(f"Copied parent output to child staging directory: {child_staging_dir}")

        if parent_source and os.path.exists(parent_source):
            child_source_dir = os.path.join(child_base_dir, 'source')
            os.makedirs(child_source_dir, exist_ok=True)
            for file in os.listdir(parent_source):
                shutil.copy(os.path.join(parent_source, file), child_source_dir)
            logger.info(f"Copied parent source to child source directory: {child_source_dir}")

    if user_code_path and user_code_path not in sys.path:
        sys.path.insert(0, user_code_path)

    if not state['agent_name']:
        with open(constructor_path, 'r', encoding='utf-8') as file:
            user_config = yaml.safe_load(file)

       # logger.info(f"Loaded user config: {user_config}")

        with open(default_path, 'r', encoding='utf-8') as file:
            default_config = yaml.safe_load(file)

        state['agent_name'] = find_agents_name(user_config)
        logger.info(f"Determined agent name: {state['agent_name']}")

        config_filename = os.path.splitext(os.path.basename(constructor_path))[0]
        if state['agent_name'] != config_filename:
            logger.error(f"Top-level key '{state['agent_name']}' does not match the filename '{config_filename}'")
            raise ValueError(f"Top-level key '{state['agent_name']}' does not match the filename '{config_filename}'")

        # Check for child pipeline
        for item in user_config[state['agent_name']]:
            if isinstance(item, dict) and 'child' in item:
                state['child_pipeline'] = item['child'][0]
                logger.info(f"Child pipeline detected: {state['child_pipeline']}")
                break
        else:
            logger.info("No child pipeline detected in the configuration.")

        # Handle nested 'agents' key
        if 'agents' in user_config[state['agent_name']]:
            user_agents = user_config[state['agent_name']]['agents']
        else:
            user_agents = [agent for agent in user_config[state['agent_name']] if isinstance(agent, dict) and 'agent_type' in agent]

        default_agent_config = default_config['default_agent_config']

        for agent in user_agents:
            if 'agent_type' in agent:
                agent_type = agent['agent_type']
                default_agent = default_agent_config.copy()
                default_agent.update(agent)
                state['agent_configs'][agent_type] = default_agent

        dependency_graph = {agent['agent_type']: agent.get('dependencies', []) for agent in user_agents if 'agent_type' in agent}
        state['execution_order'] = Utils.topological_sort(dependency_graph)
        logger.info(f"Execution order determined: {state['execution_order']}")

    # Execute parent pipeline if present
    if parent_pipeline:
        logger.info(f"Attempting to execute parent pipeline: {parent_pipeline}")
        parent_constructor_path = find_config_file(os.path.dirname(constructor_path), f"{parent_pipeline}.yml")
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

    # Process final output
    if state['ephemeral_directories']:
        final_output_folder = state['ephemeral_directories'][-1]['output_folder']
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
            
            # Debug: List contents of final_workflow_output after merging
            logger.debug("Contents of final_workflow_output after merging:")
            for root, dirs, files in os.walk(final_workflow_output):
                for file in files:
                    file_path = os.path.join(root, file)
                    logger.debug(f"  - {file_path}")
                    # Optionally, print the content of each file (be cautious with large files)
                    # with open(file_path, 'r') as f:
                    #     logger.debug(f"    Content: {json.load(f)}")
        else:
            logger.debug("No side output folder. Copying last agent's output.")
            for file in os.listdir(final_output_folder):
                src = os.path.join(final_output_folder, file)
                dst = os.path.join(final_workflow_output, file)
                shutil.copy(src, dst)
                logger.debug(f"Copied: {src} -> {dst}")
                # Optionally, print the content of each copied file
                # with open(dst, 'r') as f:
                #     logger.debug(f"  Content: {json.load(f)}")

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

    # Remove the checkpoint file
    remove_checkpoint()

    # Execute child pipeline if present
    if state['child_pipeline']:
        logger.info(f"Attempting to execute child pipeline: {state['child_pipeline']}")
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(constructor_path)))
        child_filename = f"{state['child_pipeline']}.yml"
        logger.info(f"Searching for child pipeline config in base directory: {base_dir}")
        logger.info(f"Looking for file: {child_filename}")
        child_constructor_path = find_config_file(base_dir, child_filename)
        if child_constructor_path:
            logger.info(f"Child pipeline config found at: {child_constructor_path}")
            # Pass the final output folder and source folder of the parent pipeline to the child pipeline
            parent_final_output = state['ephemeral_directories'][-1]['output_folder'] if state['ephemeral_directories'] else None
            parent_source = os.path.join(os.path.dirname(constructor_path), '..', 'agent_io', 'source')
            run_agents(child_constructor_path, user_code_path, default_path, use_tools, 
                       parent_output=parent_final_output, parent_source=parent_source)
        else:
            logger.error(f"Child pipeline config not found for: {state['child_pipeline']}")
            logger.error(f"Searched in base directory: {base_dir}")
            logger.error(f"Searched for file: {child_filename}")
    else:
        logger.info("No child pipeline to execute.")

    return final_workflow_output


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