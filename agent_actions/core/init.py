import os
import yaml
from agent_actions.logging_setup import setup_logging

logger = setup_logging()

def create_directory(path):
    """
    Create a directory if it doesn't exist.
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path)
    except Exception as e:
        logger.error(f"Failed to create directory '{path}': {e}")

def create_file(path, content=""):
    """
    Create a file if it doesn't exist.
    """
    try:
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
    except Exception as e:
        logger.error(f"Failed to create file '{path}': {e}")

def init_project(project_name):
    """
    Initialize a new Agent Actions project.
    """
    try:
        project_dir = os.path.join(os.getcwd(), project_name)
        config_dir = os.path.join(project_dir, 'agent_config')
        schema_dir = os.path.join(project_dir, 'schema')
        io_dir = os.path.join(project_dir, 'agent_io')
        config_file = os.path.join(project_dir, 'agent_actions.yml')

        # Creating directories
        create_directory(project_dir)
        create_directory(config_dir)
        create_directory(schema_dir)
        create_directory(io_dir)

        # Creating Agent Actions configuration file
        config_data = {
            "default_agent_config": {
                "api_key": "OPENAI_API_KEY",
                "model_name": "gpt-3.5-turbo",
                "chunk_config": {
                    "chunk_size": 300,
                    "overlap": 10
                }
            }
        }
        create_file(config_file, yaml.dump(config_data))

    except Exception as e:
        logger.error(f"Failed to initialize project '{project_name}': {e}")
