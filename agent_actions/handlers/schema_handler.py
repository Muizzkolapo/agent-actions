import os
import logging
from pathlib import Path
from agent_actions.handlers.file_handler import FileHandler
import yaml
from agent_actions.workflow.render_workflow import render_pipeline_with_templates
from agent_actions.cli.exceptions import (
    FileNotFoundError as AgentFileNotFoundError,
    TemplateRenderingError,
    AgentActionsError,
)

logger = logging.getLogger(__name__)


class SchemaLoader:
    """
    A class for loading schemas.
    """

    @staticmethod
    def return_schema(agent_name: str) -> set:
        try:
            agent_config_dir, _, _ = FileHandler.get_agent_paths(agent_name)
            agent_config_file = FileHandler.find_config_file(agent_config_dir, f"{agent_name}.yml")
            current_dir = Path.cwd()
            template_dir = current_dir / "templates"
            rendered_templates = render_pipeline_with_templates(agent_config_file, str(template_dir))
            data = yaml.safe_load(rendered_templates)
            dynamic_schema_names = {
                step['schema_name']
                for key, steps in data.items()
                if isinstance(steps, list)
                for step in steps
                if 'schema_name' in step
            }
            return dynamic_schema_names
        except Exception as e:
            logger.error("Error rendering schema for agent '%s': %s", agent_name, str(e))
            raise TemplateRenderingError(
                f"Error rendering schema for agent '{agent_name}': {str(e)}"
            ) from e

    @staticmethod
    def load_schema(schema_name: str) -> dict:
        """
        Retrieve and generate a JSON schema based on the schema name provided.
        Searches recursively through all directories for the schema file.

        Parameters:
            schema_name (str): The name of the schema to load.

        Returns:
            dict: The loaded schema as a dictionary.
        """
        try:
            current_dir = Path.cwd()
            # Find all files matching the schema name with .yml or .yaml extension
            schema_paths = [
                Path(root) / file
                for root, _, files in os.walk(current_dir)
                for file in files
                if file in {f"{schema_name}.yml", f"{schema_name}.yaml"}
            ]

            if not schema_paths:
                logger.error("Schema '%s' not found.", schema_name)
                raise AgentFileNotFoundError(f"Schema '{schema_name}' not found.")

            selected_path = None
            shortest_path_length = float('inf')
            for path in schema_paths:
                path_parts = list(path.parts)
                if 'schema' in path_parts:
                    # Calculate the "distance" from the root by finding the index of 'schema'
                    schema_index = len(path_parts) - path_parts[::-1].index('schema')
                    if schema_index < shortest_path_length:
                        shortest_path_length = schema_index
                        selected_path = path
            if not selected_path and schema_paths:
                selected_path = schema_paths[0]
            if not selected_path:
                logger.error("Schema '%s' not found.", schema_name)
                raise AgentFileNotFoundError(f"Schema '{schema_name}' not found.")

            with selected_path.open('r', encoding='utf-8') as file:
                documents = yaml.safe_load(file)
            return documents

        except Exception as e:
            logger.error("Error loading schema '%s': %s", schema_name, str(e))
            raise AgentActionsError(
                f"Error loading schema '{schema_name}': {str(e)}"
            ) from e

    @staticmethod
    def validate_schemas_exist(agent_name: str, directory: str) -> None:
        """
        Validates that each schema file exists anywhere in the project.
        
        Args:
            agent_name (str): The name of the agent.
            directory (str): The base directory to start searching from.
        
        Raises:
            SingleSchemaMissingError: If one schema file is missing.
            MultipleSchemaMissingError: If multiple schema files are missing.
        """
        schema_names = SchemaLoader.return_schema(agent_name)
        missing_files = []
        for schema_name in schema_names:
            try:
                if not SchemaLoader.load_schema(schema_name):
                    missing_files.append(f"{schema_name}.yml")
            except FileNotFoundError:
                missing_files.append(f"{schema_name}.yml")
        if missing_files:
            if len(missing_files) == 1:
                msg = f"Schema file missing: {missing_files[0]}"
            else:
                msg = f"Multiple schema files missing: {', '.join(missing_files)}"
            logger.error(msg)
            raise AgentFileNotFoundError(msg)
