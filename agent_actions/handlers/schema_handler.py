import traceback
import os 
from agent_actions.handlers.file_handler import FileHandler
import logging
import yaml
from agent_actions.logging_setup import setup_logging


class SchemaLoader:
    """
    A class for loading schemas.
    """

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



