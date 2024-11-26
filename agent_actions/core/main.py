import os
import sys
import yaml
import click
from jinja2 import Environment, FileSystemLoader
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.core.agent_runners import AgentWorkflow  
from agent_actions.handlers.agent_handlers import AgentManager  
from agent_actions.docs.app import run_app
from agent_actions.core.init import init_project
from agent_actions.logging_setup import setup_logging
from agent_actions.processors.render_template import render_pipeline_with_templates  

logger = setup_logging()

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
        logger.error(f"Failed to initialize project '{project_name}': {e}")
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
        logger.error(f"Failed to start documentation server: {e}")
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

    for required_dir in [agent_config_dir, schema_dir, io_dir]:
        if not os.path.exists(required_dir):
            logger.error(f"Missing directory: {required_dir}")
            sys.exit(1)

    if not filename.endswith(".yml"):
        filename += ".yml"
    full_path = FileHandler.find_config_file(agent_config_dir, filename)

    if full_path is None or not os.path.exists(default_config_path):
        logger.error(f"Missing configuration file: {filename}")
        sys.exit(1)

    project_dir = os.path.abspath(current_dir)
    if not ConfigValidator.check_agent_file_unique(full_path, project_dir):
        logger.error(f"Duplicate configuration file: {full_path}")
        sys.exit(1)

    agent_name = os.path.splitext(filename)[0]
    if not ConfigValidator.check_agent_name_unique(agent_name, project_dir):
        logger.error(f"Duplicate agent name: {agent_name}")
        sys.exit(1)

    try:
        current_dir = os.getcwd()
        template_dir = os.path.join(current_dir, "templates")
        config_data = render_pipeline_with_templates(full_path,template_dir)
        config_data = yaml.safe_load(config_data)


        if agent_name not in config_data:
            logger.error(f"Missing top-level key '{agent_name}' in configuration file.")
            sys.exit(1)

        agent_config = config_data[agent_name]

        if not isinstance(agent_config, list):
            logger.error(f"Invalid configuration format for '{filename}'")
            sys.exit(1)

        agent_entries = [entry for entry in agent_config if 'agent_type' in entry]

        is_valid, message = ConfigValidator.validate_agent_config(agent_entries)
        if not is_valid:
            logger.error(f"Validation error: {message}")
            sys.exit(1)

        use_tools = user_code is not None
        parent_pipeline = next(
            (item.get('parent', [None])[0] for item in agent_config if isinstance(item, dict) and 'parent' in item),
            None
        )

        # Create an instance of AgentWorkflow and run it
        workflow = AgentWorkflow(
            constructor_path=full_path,
            user_code_path=user_code,
            default_path=default_config_path,
            use_tools=use_tools,
            parent_pipeline=parent_pipeline
        )
        workflow.run()

    except (ValueError, FileNotFoundError, yaml.YAMLError) as e:
        logger.error(f"Failed to run agent workflow: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)

@main.command()
@click.option('-a', '--agent', required=True, help="Agent name")
def clean(agent):
    """Clean agent directories."""
    try:
        AgentManager.clean_agent_directories(agent)
    except Exception as e:
        logger.error(f"Failed to clean agent directories for '{agent}': {e}")
        sys.exit(1)

@main.command()
@click.argument('agent_name')
def render(agent_name):
    """Render a Jinja template for the specified agent."""
    try:
        agent_config_dir, _, _ = FileHandler.get_agent_paths(agent_name)
        agent_config_file = FileHandler.find_config_file(agent_config_dir, f"{agent_name}.yml")
        current_dir = os.getcwd()
        template_dir = os.path.join(current_dir, "templates")
        demo = render_pipeline_with_templates(agent_config_file,template_dir)
        print(demo)


    except Exception as e:
        logger.error(f"Failed to render template for agent '{agent_name}': {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
