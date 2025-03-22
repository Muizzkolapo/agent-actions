
"""
Run command for the Agent Actions CLI.
"""

import os
import yaml
import click
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass

from agent_actions.workflow.agent_workflow import AgentWorkflow
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.handlers.schema_handler import SchemaLoader
from agent_actions.workflow.render_workflow import render_pipeline_with_templates
from agent_actions.cli.validators.prompt_validator import PromptValidator
from agent_actions.cli.validators.directory_validator import DirectoryValidator
from agent_actions.cli.validators.config_validator import ConfigurationValidator
from agent_actions.cli.validators.schema_validator import SchemaValidator
from agent_actions.cli.services.config_renderer import ConfigRenderer
from agent_actions.cli.services.agent_config_parser import AgentConfigParser
from agent_actions.cli.services.project_paths_factory import ProjectPathsFactory
from agent_actions.cli.services.agent_runner_service import AgentRunnerService

logger = logging.getLogger(__name__)


@click.command()
@click.option('-a', '--agent', required=True,
              help="Agent configuration file name without path or extension")
@click.option('-u', '--user_code', help="Path to the user's code folder containing UDFs")
def run(agent: str, user_code: Optional[str]) -> None:
    """
    Run agents with a specified agent configuration.

    Args:
        agent: Name of the agent configuration to run.
        user_code: Path to user-defined functions directory.
    """
    try:
        # Prepare filename and extract agent name
        filename = f"{agent}.yml" if not agent.endswith(".yml") else agent
        agent_name = Path(filename).stem
        
        # Create project paths
        paths = ProjectPathsFactory.create_project_paths(agent_name, filename)
        
        # Validate prompts
        PromptValidator.validate_prompts(paths.prompt_dir)
        
        # Check required directories
        required_dirs = [paths.agent_config_dir, paths.schema_dir, paths.io_dir]
        DirectoryValidator.check_required_directories(required_dirs)
        
        # Find configuration file
        full_path = AgentRunnerService.find_config_file(paths.agent_config_dir, filename)
        if full_path is None or not paths.default_config_path.exists():
            raise ValueError(f"Missing configuration file: {filename}")
        
        # Validate agent configuration
        ConfigurationValidator.validate_agent_config(agent_name, full_path, paths.current_dir)
        
        # Render and load configuration
        config_data = ConfigRenderer.render_and_load_config(
            agent_name, 
            full_path, 
            paths.template_dir, 
            paths.rendered_workflows_dir
        )
        
        # Validate schema
        SchemaValidator.validate_schema(agent_name, paths.schema_dir)
        
        # Validate agent entries
        if agent_name not in config_data:
            available = list(config_data.keys())
            raise ValueError(f"Workflow '{agent_name}' not found in configuration. Available: {available}")
        
        agent_config = config_data[agent_name]
        ConfigurationValidator.validate_agent_entries(agent_config, agent_name)
        
        # Get parent pipeline and run workflow
        parent_pipeline = AgentConfigParser.get_parent_pipeline(agent_config)
        AgentRunnerService.run_agent_workflow(
            agent_name,
            full_path,
            paths.default_config_path,
            user_code,
            parent_pipeline
        )
    except Exception as e:
        raise ValueError(f"Failed to run agent {agent}: {str(e)}")