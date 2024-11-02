import os
import sys
import yaml
import click
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.core.agent_runners import run_agents
from agent_actions.core.agent_runners import AgentManager
from agent_actions.docs.app import run_app
from agent_actions.core.init import init_project

from agent_actions.logging_setup import setup_logging
logger = setup_logging()

logger.info("Initializing command")

@click.group()
def main():
    """Agent CLI Tool"""
    pass

@main.command()
@click.argument('project_name')
def init(project_name):
    """Initialize a new Agent Actions project."""
    try:
        init_project(project_name)
    except Exception as e:
        logger.error(f"An error occurred during initialization: {e}")
        sys.exit(1)

@main.command()
@click.option('--host', default='0.0.0.0', help='Host for the Flask app.')
@click.option('--port', default=8000, help='Port for the Flask app.')
@click.option('--debug', is_flag=True, default=False, help='Run the Flask app in debug mode.')
def docs(host, port, debug):
    """Generate or display agent documentation."""
    try:
        run_app(host, port, debug)
    except Exception as e:
        logger.error(f"An error occurred while generating docs: {e}")
        sys.exit(1)


@main.command()
@click.option('-a', '--agent', required=True, help="Name of the schema (agent configuration file without path)")
@click.option('-u', '--user_code', help="Path to the user's code folder containing UDFs")
def run(agent, user_code):
    """Run agents with a specified agent configuration."""

    filename = agent
    current_dir = os.getcwd()
    agent_config_dir, io_dir, _ = FileHandler.get_agent_paths(filename)
    schema_dir = os.path.join(current_dir, 'schema')
    default_config_path = os.path.join(current_dir, 'agent_actions.yml')

    # Check for required directories
    for required_dir in [agent_config_dir, schema_dir, io_dir]:
        if not os.path.exists(required_dir):
            logger.error(f"Missing directory: {required_dir}")
            sys.exit(1)

    # Ensure correct file extension
    if not filename.endswith(".yml"):
        filename += ".yml"
    full_path = FileHandler.find_config_file(agent_config_dir, filename)

    if full_path is None or not os.path.exists(default_config_path):
        logger.error(f"Missing configuration file: {filename}")
        sys.exit(1)

    project_dir = os.path.abspath(os.path.join(current_dir))
    if not ConfigValidator.check_agent_file_unique(full_path, project_dir):
        logger.error(f"Duplicate configuration file: {full_path}")
        sys.exit(1)

    agent_name = os.path.splitext(filename)[0]
    if not ConfigValidator.check_agent_name_unique(agent_name, project_dir):
        logger.error(f"Duplicate agent name: {agent_name}")
        sys.exit(1)

    with open(full_path, 'r') as config_file:
        config_data = yaml.safe_load(config_file)

    if agent_name not in config_data:
        logger.error(f"Missing top-level key '{agent_name}' in configuration file.")
        sys.exit(1)

    agent_config = config_data[agent_name]

    # Validate configuration entries
    udf_entries = [entry for entry in agent_config if 'udf' in entry]
    agent_entries = [entry for entry in agent_config if 'agent_type' in entry]
    if not isinstance(agent_config, list):
        logger.error(f"Invalid configuration format for '{filename}'")
        sys.exit(1)

    is_valid, message = ConfigValidator.validate_agent_config(agent_entries)
    if not is_valid:
        logger.error(f"Validation error: {message}")
        sys.exit(1)

    use_tools = user_code is not None

    # Extract parent pipeline information
    parent_pipeline = next((item.get('parent', [None])[0] for item in agent_config if isinstance(item, dict) and 'parent' in item), None)

    try:
        run_agents(full_path, user_code, default_config_path, use_tools, parent_pipeline=parent_pipeline)
    except (ValueError, FileNotFoundError, yaml.YAMLError) as e:
        logger.error(f"Execution error: {e}")
        sys.exit(1)

@main.command()
@click.option('-a', '--agent', required=True, help="Agent name")
def clean(agent):
    """Clean agent directories."""
    AgentManager.clean_agent_directories(agent)

if __name__ == "__main__":
    main()
