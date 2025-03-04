"""
Command-line interface for the Agent Actions framework.
"""

import os
import click
import yaml
from typing import Optional, List, Dict, Any

from agent_actions.workflow.agent_workflow import AgentWorkflow
from agent_actions.core.init import init_project
from agent_actions.docs.app import run_app
from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.handlers.schema_handler import SchemaLoader
from agent_actions.workflow.render_workflow import render_pipeline_with_templates

# Import new error handling utilities
from agent_actions.core.error_utils import cli_command, try_operation, handle_errors

# Import new exception classes
from agent_actions.core.exceptions import (
    DirectoryError,
    DuplicateConfigError,
    MissingConfigError,
    MissingSchemaError,
    InvalidConfigError,
    WorkflowNameMismatchError,
    ProjectInitError,
    DocsServerError,
    WorkflowExecutionError,
    CleanupError,
    TemplateRenderError,
    ErrorCategory,
)


@handle_errors(error_category=ErrorCategory.CONFIGURATION)
def validate_prompts(prompt_dir: str) -> None:
    """
    Validate unique prompts in the prompt_store directory.

    Args:
        prompt_dir: Path to the prompt_store directory

    Raises:
        InvalidConfigError: If prompt validation fails
    """
    if not os.path.exists(prompt_dir):
        return

    def _process_prompts():
        for prompt_file in os.listdir(prompt_dir):
            if prompt_file.endswith('.md'):
                file_path = os.path.join(prompt_dir, prompt_file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    PromptLoader.validate_unique_prompts(prompt_file, content)

    try_operation(
        _process_prompts,
        f"Failed to validate prompts in {prompt_dir}",
        InvalidConfigError,
        config_path=prompt_dir
    )


@handle_errors(error_category=ErrorCategory.FILE_SYSTEM)
def check_required_directories(required_dirs: List[str]) -> None:
    """
    Check if required directories exist.

    Args:
        required_dirs: List of directory paths to check

    Raises:
        DirectoryError: If a required directory doesn't exist
    """
    for required_dir in required_dirs:
        if not os.path.exists(required_dir):
            raise DirectoryError(
                directory=required_dir,
                reason="Required directory does not exist",
                recovery_hint=f"Create the directory at {required_dir}"
            )


@handle_errors(error_category=ErrorCategory.CONFIGURATION)
def validate_agent_config(agent_name: str, config_path: str, project_dir: str) -> None:
    """
    Validate the agent configuration file.

    Args:
        agent_name: Name of the agent
        config_path: Path to the agent configuration file
        project_dir: Path to the project directory

    Raises:
        DuplicateConfigError: If the agent configuration file is duplicated
        InvalidConfigError: If the agent configuration is invalid
    """
    # Check if the agent file is unique
    def _check_file_unique():
        return ConfigValidator.check_agent_file_unique(config_path, project_dir)

    is_unique = try_operation(
        _check_file_unique,
        f"Failed to check if agent file is unique: {agent_name}",
        InvalidConfigError,
        config_path=config_path
    )

    if not is_unique:
        raise DuplicateConfigError(
            config_path=config_path,
            recovery_hint="Rename one of the duplicate agent configuration files"
        )

    # Check if the agent name is unique
    def _check_name_unique():
        return ConfigValidator.check_agent_name_unique(agent_name, project_dir)

    is_name_unique, error_msg = try_operation(
        _check_name_unique,
        f"Failed to check if agent name is unique: {agent_name}",
        InvalidConfigError,
        config_path=config_path
    )

    if not is_name_unique:
        raise InvalidConfigError(
            config_path=config_path,
            reason=error_msg or f"Agent name is not unique: {agent_name}",
            recovery_hint="Use a unique name for your agent"
        )


@handle_errors(error_category=ErrorCategory.CONFIGURATION)
def render_and_load_config(
    agent_name: str,
    config_path: str,
    template_dir: str,
    output_dir: str
) -> Dict[str, Any]:
    """
    Render templates and load configuration data.

    Args:
        agent_name: Name of the agent
        config_path: Path to the agent configuration file
        template_dir: Path to the template directory
        output_dir: Path to the output directory

    Returns:
        Parsed configuration data as a dictionary

    Raises:
        TemplateRenderError: If template rendering fails
        InvalidConfigError: If YAML parsing fails
    """
    # Create output directory if it doesn't exist
    try_operation(
        lambda: os.makedirs(output_dir, exist_ok=True),
        f"Failed to create output directory: {output_dir}",
        DirectoryError,
        directory=output_dir
    )

    output_path = os.path.join(output_dir, f"{agent_name}.yml")

    # Render the template
    config_data = try_operation(
        lambda: render_pipeline_with_templates(config_path, template_dir, output_path),
        f"Failed to render template for {agent_name}",
        TemplateRenderError,
        template_name=agent_name
    )

    # Parse YAML
    return try_operation(
        lambda: yaml.safe_load(config_data),
        f"Failed to parse YAML for {agent_name}",
        InvalidConfigError,
        config_path=config_path,
        recovery_hint="Check your YAML syntax in the configuration file"
    )


@handle_errors(error_category=ErrorCategory.CONFIGURATION)
def validate_schema(agent_name: str, schema_dir: str) -> None:
    """
    Validate that the required schemas exist.

    Args:
        agent_name: Name of the agent
        schema_dir: Path to the schema directory

    Raises:
        MissingSchemaError: If the required schema is missing
    """
    schema_error = try_operation(
        lambda: SchemaLoader.validate_schemas_exist(agent_name, schema_dir),
        f"Failed to validate schema for {agent_name}",
        MissingSchemaError,
        agent_name=agent_name
    )

    if schema_error:
        raise MissingSchemaError(
            agent_name=agent_name,
            schema_path=os.path.join(schema_dir, f"{agent_name}.json"),
            recovery_hint=f"Create the required schema file for {agent_name} in {schema_dir}"
        )


@handle_errors(error_category=ErrorCategory.CONFIGURATION)
def validate_agent_entries(agent_config: Any, agent_name: str) -> None:
    """
    Validate the agent entries in the configuration.

    Args:
        agent_config: Agent configuration data
        agent_name: Name of the agent

    Raises:
        InvalidConfigError: If the agent configuration is invalid
    """
    if not isinstance(agent_config, list):
        raise InvalidConfigError(
            config_path=agent_name,
            reason="Agent configuration must be a list",
            recovery_hint="Update your configuration to be a list of agent entries"
        )

    agent_entries = [entry for entry in agent_config if 'agent_type' in entry]

    def _validate_config():
        return ConfigValidator.validate_agent_config(agent_entries)

    is_valid, message = try_operation(
        _validate_config,
        f"Failed to validate agent configuration for {agent_name}",
        InvalidConfigError,
        config_path=agent_name
    )

    if not is_valid:
        raise InvalidConfigError(
            config_path=agent_name,
            reason=message or "Invalid agent configuration format",
            recovery_hint="Check your agent configuration against the schema"
        )


@handle_errors(error_category=ErrorCategory.WORKFLOW)
def get_parent_pipeline(agent_config: List[Dict[str, Any]]) -> Optional[str]:
    """
    Get the parent pipeline from the agent configuration.

    Args:
        agent_config: Agent configuration data

    Returns:
        Parent pipeline name if found, None otherwise
    """
    for item in agent_config:
        if isinstance(item, dict) and 'parent' in item:
            parent_list = item.get('parent')
            if isinstance(parent_list, list) and len(parent_list) > 0:
                return parent_list[0]
    return None


@click.group()
def main():
    """Agent Actions CLI Tool - Framework for constructing and running agent workflows"""
    pass


@main.command()
@click.argument('project_name')
@cli_command
def init(project_name: str) -> None:
    """
    Initialize a new Agent Actions project.

    Args:
        project_name: Name of the project to create
    """
    try:
        init_project(project_name)
    except Exception as e:
        raise ProjectInitError(
            project_name=project_name,
            reason=str(e)
        )


@main.command()
@click.option('--host', default='0.0.0.0', help='Host for the documentation server.')
@click.option('--port', default=8000, type=int, help='Port for the documentation server.')
@click.option('--debug', is_flag=True, default=False, help='Run the server in debug mode.')
@cli_command
def docs(host: str, port: int, debug: bool) -> None:
    """
    Generate or display agent documentation.

    Args:
        host: Host address to serve documentation
        port: Port number to serve documentation
        debug: Whether to run the server in debug mode
    """
    try:
        run_app(host, port, debug)
    except Exception as e:
        raise DocsServerError(
            reason=str(e),
            recovery_hint="Check network configuration and ensure port is available"
        )


@main.command()
@click.option('-a', '--agent', required=True,
              help="Agent configuration file name without path or extension")
@click.option('-u', '--user_code', help="Path to the user's code folder containing UDFs")
@cli_command
def run(agent: str, user_code: Optional[str]) -> None:
    """
    Run agents with a specified agent configuration.

    Args:
        agent: Name of the agent configuration to run
        user_code: Path to user-defined functions directory
    """
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

    # Find configuration file
    full_path = FileHandler.find_config_file(agent_config_dir, filename)
    if full_path is None or not os.path.exists(default_config_path):
        raise MissingConfigError(
            config_path=filename,
            recovery_hint=f"Create the configuration file {filename} in {agent_config_dir}"
        )

    project_dir = os.path.abspath(current_dir)
    validate_agent_config(agent_name, full_path, project_dir)

    # Render templates and load configuration data
    template_dir = os.path.join(current_dir, "templates")
    rendered_workflows_dir = os.path.join(current_dir, "rendered_workflows")
    config_data = render_and_load_config(agent_name, full_path, template_dir, rendered_workflows_dir)

    # Perform validations that depend on config_data
    validate_schema(agent_name, schema_dir)

    if agent_name not in config_data:
        raise WorkflowNameMismatchError(
            requested_name=agent_name,
            available_names=list(config_data.keys()),
            recovery_hint=f"Ensure the workflow '{agent_name}' is defined in the configuration"
        )

    agent_config = config_data[agent_name]
    validate_agent_entries(agent_config, agent_name)

    # Proceed with processing
    use_tools = user_code is not None
    parent_pipeline = get_parent_pipeline(agent_config)

    # Run the workflow
    def _run_workflow():
        workflow = AgentWorkflow(
            constructor_path=full_path,
            user_code_path=user_code,
            default_path=default_config_path,
            use_tools=use_tools,
            parent_pipeline=parent_pipeline
        )
        return workflow.run()

    try_operation(
        _run_workflow,
        f"Failed to execute workflow for agent {agent_name}",
        WorkflowExecutionError,
        workflow_name=agent_name,
        recovery_hint="Check logs for detailed error information"
    )


@main.command()
@click.option('-a', '--agent', required=True, help="Agent name")
@cli_command
def clean(agent: str) -> None:
    """
    Clean agent directories.

    Args:
        agent: Name of the agent to clean
    """
    def _clean_agent():
        return AgentManager.clean_agent_directories(agent)

    try_operation(
        _clean_agent,
        f"Failed to clean directories for agent {agent}",
        CleanupError,
        agent_name=agent,
        recovery_hint="Ensure no processes are using files in the agent directories"
    )


@main.command()
@click.argument('agent_name')
@cli_command
def render(agent_name: str) -> None:
    """
    Render a Jinja template for the specified agent.

    Args:
        agent_name: Name of the agent template to render
    """
    # Get agent paths
    agent_config_dir, _, _ = FileHandler.get_agent_paths(agent_name)

    # Find configuration file
    agent_config_file = FileHandler.find_config_file(agent_config_dir, f"{agent_name}.yml")

    if not agent_config_file:
        raise MissingConfigError(
            config_path=f"{agent_name}.yml",
            recovery_hint=f"Create the configuration file {agent_name}.yml in {agent_config_dir}"
        )

    # Render template
    current_dir = os.getcwd()
    template_dir = os.path.join(current_dir, "templates")

    rendered_template = try_operation(
        lambda: render_pipeline_with_templates(agent_config_file, template_dir),
        f"Failed to render template for agent {agent_name}",
        TemplateRenderError,
        template_name=agent_name,
        recovery_hint="Check Jinja template syntax and variables"
    )

    print(rendered_template)


if __name__ == "__main__":
    main()
