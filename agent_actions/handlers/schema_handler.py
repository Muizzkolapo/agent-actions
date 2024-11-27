import traceback
import os 
from agent_actions.handlers.file_handler import FileHandler
import logging
import yaml
from agent_actions.logging_setup import setup_logging
import sys
from agent_actions.processors.render_template import render_pipeline_with_templates  
logger = setup_logging()


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
            render_templates = render_pipeline_with_templates(agent_config_file,template_dir)
            data = yaml.safe_load(render_templates)
            dynamic_schema_names = set()

            for key, steps in data.items():
                if isinstance(steps, list): 
                    for step in steps:
                        if 'schema_name' in step:  
                            dynamic_schema_names.add(step['schema_name'])

            return dynamic_schema_names



        except Exception as e:
            logger.error(f"Failed to render template for agent '{agent_name}': {e}")
            sys.exit(1)

    @staticmethod
    def load_schema(schema_name):
        """
        Retrieve and generate a JSON schema based on the schema name provided.

        Parameters:
            schema_name (str): The name of the schema to load.

        Returns:
            dict: The loaded schema as a dictionary.
        """
        try:
            current_dir = os.getcwd()
            schema_dir = os.path.join(current_dir, "schema")

            if not os.path.exists(schema_dir):
                raise FileNotFoundError("Schema directory not found.")

            schema_file_path = FileHandler.find_file_in_directory(schema_dir, f"{schema_name}.yml")

            if not schema_file_path:
                raise FileNotFoundError(f"Schema file not found: {schema_name}.yml")

            with open(schema_file_path, 'r', encoding='utf-8') as file:
                documents = yaml.safe_load(file)

            return documents

        except Exception as e:
            print(f"An error occurred in load_schema: {e}")
            traceback.print_exc()
            return None


    @staticmethod  
    def validate_schemas_exist(agent_name, directory):
        """
        Validates that each schema file exists in the given directory.
        
        Args:
            schema_names (list): A list of schema names to validate.
            directory (str): The directory to check for schema files.
        
        Returns:
            None: If all schema files exist.
            Raises FileNotFoundError: If any schema file is missing.
        """
        schema_names = SchemaLoader.return_schema(agent_name)
        missing_files = []
        for schema_name in schema_names:
            schema_file = f"{schema_name}.yml"
            schema_path = os.path.join(directory, schema_file)
            if not os.path.isfile(schema_path):
                missing_files.append(schema_file)
        
        if missing_files:
            if len(missing_files) == 1:
                raise FileNotFoundError(f"The schema file '{missing_files[0]}' is missing.")
            else:
                raise FileNotFoundError(f"The following schema files are missing: {', '.join(missing_files)}")