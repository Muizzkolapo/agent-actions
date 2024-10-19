import os
import sys
import yaml
import click
from agent_actions.logging_setup import logger
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.core.agent_runners import run_agents
from agent_actions.core.agent_runners import AgentManager

@click.group()
def main():
    """Main entry point for the CLI."""
    pass

@main.command()
@click.option('-a', '--agent', required=True, help="Name of the schema (agent configuration file without path)")
@click.option('-u', '--user_code', help="Path to the user's code folder containing UDFs")
def run(agent, user_code):
    """Run agents with a specified agent configuration."""
    logger.info("Starting agent execution.")
    logger.info(f"Command-line arguments: agent={agent}, user_code={user_code}")

    filename = agent
    current_dir = os.getcwd()
    agent_config_dir, io_dir, _ = FileHandler.get_agent_paths(filename)
    schema_dir = os.path.join(current_dir, 'schema')

    default_config_path = os.path.join(current_dir, 'agent_actions.yml')

    required_dirs = [agent_config_dir, schema_dir, io_dir]
    for required_dir in required_dirs:
        if not os.path.exists(required_dir):
            logger.error(f"The directory '{required_dir}' does not exist.")
            sys.exit(1)

    if not filename.endswith(".yml"):
        filename += ".yml"
    full_path = FileHandler.find_config_file(agent_config_dir, filename)

    if full_path is None:
        logger.error(f"The configuration file '{filename}' does not exist in '{agent_config_dir}'.")
        sys.exit(1)

    if not os.path.exists(default_config_path):
        logger.error(f"The default configuration file does not exist in '{current_dir}'.")
        sys.exit(1)

    project_dir = os.path.abspath(os.path.join(current_dir))
    if not ConfigValidator.check_agent_file_unique(full_path, project_dir):
        logger.error(f"'{full_path}' is not unique across the entire project.")
        sys.exit(1)

    agent_name = os.path.splitext(filename)[0]
    logger.info(f"Agent name determined: {agent_name}")

    if not ConfigValidator.check_agent_name_unique(agent_name, project_dir):
        logger.error(f"The agent name '{agent_name}' is not unique across the entire project.")
        sys.exit(1)

    with open(full_path, 'r') as config_file:
        config_data = yaml.safe_load(config_file)

    if agent_name not in config_data:
        logger.error(f"The top-level key '{agent_name}' is not found in the configuration file.")
        sys.exit(1)

    agent_config = config_data[agent_name]

    udf_entries = [entry for entry in agent_config if 'udf' in entry]
    agent_entries = [entry for entry in agent_config if 'agent_type' in entry]

    logger.info(f"Loaded configuration for '{agent_name}' with {len(agent_entries)} agents.")
    for idx, agent_entry in enumerate(agent_entries):
        if 'agent_type' in agent_entry:
            logger.info(f"  Agent {idx + 1}: {agent_entry['agent_type']}")

    if not isinstance(agent_config, list):
        logger.error(f"The configuration for '{filename}' is not a list.")
        sys.exit(1)

    is_valid, message = ConfigValidator.validate_agent_config(agent_entries)
    if not is_valid:
        logger.error(f"Validation error: {message}")
        sys.exit(1)

    use_tools = user_code is not None

    # Extract parent pipeline information
    parent_pipeline = None
    for item in agent_config:
        if isinstance(item, dict) and 'parent' in item:
            parent_pipeline = item['parent']
            if isinstance(parent_pipeline, list):
                parent_pipeline = parent_pipeline[0]  # Take the first item if it's a list
            break

    logger.info(f"Parent pipeline detected: {parent_pipeline}")

    try:
        run_agents(full_path, user_code, default_config_path, use_tools, parent_pipeline=parent_pipeline)
    except ValueError as ve:
        logger.error(f"Configuration error: {ve}. Please make sure the top-level key in the YAML file matches the filename.")
        sys.exit(1)
    except FileNotFoundError as fe:
        logger.error(f"File not found: {fe}")
        sys.exit(1)
    except yaml.YAMLError as ye:
        logger.error(f"YAML parsing error: {ye}")
        sys.exit(1)

@main.command()
@click.option('-a', '--agent', required=True, help="Agent name")
def clean(agent):
    """Clean agent directories."""
    AgentManager.clean_agent_directories(agent)

if __name__ == "__main__":
    main()
