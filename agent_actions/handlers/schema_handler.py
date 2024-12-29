import os 
from agent_actions.handlers.file_handler import FileHandler
import yaml
from agent_actions.workflow.render_workflow import render_pipeline_with_templates
import sys
from agent_actions.exceptions import (
    raise_schema_not_found_error,
    raise_schema_render_error,
    raise_multiple_schema_missing_error,
    raise_single_schema_missing_error
)

class SchemaLoader:
    """
    A class for loading schemas.
    """
    @staticmethod
    def return_schema(agent_name):
        try:
            agent_config_dir, _, _ = FileHandler.get_agent_paths(agent_name)
            agent_config_file = FileHandler.find_config_file(agent_config_dir, f"{agent_name}.yml")
            current_dir = os.getcwd()
            template_dir = os.path.join(current_dir, "templates")
            render_templates = render_pipeline_with_templates(agent_config_file, template_dir)
            data = yaml.safe_load(render_templates)
            dynamic_schema_names = set()

            for key, steps in data.items():
                if isinstance(steps, list): 
                    for step in steps:
                        if 'schema_name' in step:  
                            dynamic_schema_names.add(step['schema_name'])

            return dynamic_schema_names

        except Exception as e:
            raise_schema_render_error(agent_name, str(e))

    @staticmethod
    def load_schema(schema_name):
        """
        Retrieve and generate a JSON schema based on the schema name provided.
        Searches recursively through all directories for the schema file.

        Parameters:
            schema_name (str): The name of the schema to load.

        Returns:
            dict: The loaded schema as a dictionary.
        """
        try:
            current_dir = os.getcwd()
            schema_paths = []

            for root, _, files in os.walk(current_dir):
                for file in files:
                    if file == f"{schema_name}.yml" or file == f"{schema_name}.yaml":
                        schema_paths.append(os.path.join(root, file))

            if not schema_paths:
                raise_schema_not_found_error(schema_name)

            selected_path = None
            shortest_path_length = float('inf')
            
            for path in schema_paths:
                path_parts = path.split(os.sep)
                if 'schema' in path_parts:
                    schema_index = len(path_parts) - path_parts[::-1].index('schema')
                    if schema_index < shortest_path_length:
                        shortest_path_length = schema_index
                        selected_path = path
            if not selected_path and schema_paths:
                selected_path = schema_paths[0]

            if not selected_path:
                raise_schema_not_found_error(schema_name)

            with open(selected_path, 'r', encoding='utf-8') as file:
                documents = yaml.safe_load(file)

            return documents

        except Exception as e:
            raise_schema_render_error(schema_name, str(e))

    @staticmethod  
    def validate_schemas_exist(agent_name, directory):
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
                raise_single_schema_missing_error(missing_files[0])
            else:
                raise_multiple_schema_missing_error(missing_files)