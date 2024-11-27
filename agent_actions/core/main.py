import os
import sys

import click
import yaml

from agent_actions.core.agent_runners import AgentWorkflow
from agent_actions.core.init import init_project
from agent_actions.docs.app import run_app
from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.handlers.schema_handler import SchemaLoader
from agent_actions.logging_setup import setup_logging
from agent_actions.processors.render_template import render_pipeline_with_templates

logger = setup_logging()

# Helper functions
def validate_prompts(prompt_dir):
    """Validate unique prompts in the prompt_store directory."""
    if not os.path.exists(prompt_dir):
        return
    for prompt_file in os.listdir(prompt_dir):
        if prompt_file.endswith('.md'):
            file_path = os.path.join(prompt_dir, prompt_file)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                PromptLoader.validate_unique_prompts(prompt_file, content)

def check_required_directories(required_dirs):
    """Check if required directories exist."""
    for required_dir in required_dirs:
        if not os.path.exists(required_dir):
            logger.error(f"Missing directory: {required_dir}")
            sys.exit(1)

def validate_agent_config(agent_name, full_path, project_dir):
    """Validate the agent configuration file."""
    if not ConfigValidator.check_agent_file_unique(full_path, project_dir):
        logger.error(f"Duplicate configuration file: {full_path}")
        sys.exit(1)
    is_unique, error_msg = ConfigValidator.check_agent_name_unique(agent_name, project_dir)
    if not is_unique:
        logger.error(error_msg)
        sys.exit(1)

def render_and_load_config(agent_name, full_path, template_dir, rendered_workflows_dir):
    """Render templates and load configuration data."""
    os.makedirs(rendered_workflows_dir, exist_ok=True)
    rendered_workflow = os.path.join(rendered_workflows_dir, f"{agent_name}.yml")
    config_data = render_pipeline_with_templates(full_path, template_dir, rendered_workflow)
    return yaml.safe_load(config_data)

def validate_schema(agent_name, schema_dir):
    """Validate that the required schemas exist."""
    schema_error = SchemaLoader.validate_schemas_exist(agent_name, schema_dir)
    if schema_error:
        logger.error(f"Missing schema for agent '{agent_name}'")
        sys.exit(1)

def validate_agent_entries(agent_config):
    """Validate the agent entries in the configuration."""
    if not isinstance(agent_config, list):
        logger.error("Invalid configuration format for the agent.")
        sys.exit(1)
    agent_entries = [entry for entry in agent_config if 'agent_type' in entry]
    is_valid, message = ConfigValidator.validate_agent_config(agent_entries)
    if not is_valid:
        logger.error(f"Validation error: {message}")
        sys.exit(1)

def get_parent_pipeline(agent_config):
    """Get the parent pipeline from the agent configuration."""
    for item in agent_config:
        if isinstance(item, dict) and 'parent' in item:
            return item.get('parent')[0]
    return None

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
@click.option('-a', '--agent', required=True, help="Agent configuration file name without path or extension")
@click.option('-u', '--user_code', help="Path to the user's code folder containing UDFs")
def run(agent, user_code):
    """Run agents with a specified agent configuration."""
    try:
        # Set up paths
        current_dir = os.getcwd()
        prompt_dir = os.path.join(current_dir, "prompt_store")
        filename = f"{agent}.yml" if not agent.endswith(".yml") else agent
        agent_name = os.path.splitext(filename)[0]
        agent_config_dir, io_dir, _ = FileHandler.get_agent_paths(agent_name)
        schema_dir = os.path.join(current_dir, 'schema')
        default_config_path = os.path.join(current_dir, 'agent_actions.yml')
        required_dirs = [agent_config_dir, schema_dir, io_dir]

        # Perform validations that don't depend on config_data
        validate_prompts(prompt_dir)
        check_required_directories(required_dirs)
        full_path = FileHandler.find_config_file(agent_config_dir, filename)
        if full_path is None or not os.path.exists(default_config_path):
            logger.error(f"Missing configuration file: {filename}")
            sys.exit(1)
        project_dir = os.path.abspath(current_dir)
        validate_agent_config(agent_name, full_path, project_dir)

        # Render templates and load configuration data
        template_dir = os.path.join(current_dir, "templates")
        rendered_workflows_dir = os.path.join(current_dir, "rendered_workflows")
        config_data = render_and_load_config(agent_name, full_path, template_dir, rendered_workflows_dir)

        # Perform validations that depend on config_data
        validate_schema(agent_name, schema_dir)
        if agent_name not in config_data:
            logger.error(
                f"The config file name '{agent_name}' does not match any workflow names {list(config_data.keys())}."
            )
            sys.exit(1)
        agent_config = config_data[agent_name]
        validate_agent_entries(agent_config)

        # Proceed with processing
        use_tools = user_code is not None
        parent_pipeline = get_parent_pipeline(agent_config)

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
        rendered_template = render_pipeline_with_templates(agent_config_file, template_dir)
        print(rendered_template)
    except Exception as e:
        logger.error(f"Failed to render template for agent '{agent_name}': {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
