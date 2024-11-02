import os
import yaml
from agent_actions.logging_setup import setup_logging

# Initialize logger
logger = setup_logging()

def create_directory(path):
    """
    Create a directory if it doesn't exist.
    """
    try:
        logger.debug(f"Checking if directory exists: {path}")
        if not os.path.exists(path):
            os.makedirs(path)
            logger.info(f"Created directory: {path}")
        else:
            logger.warning(f"Directory already exists: {path}")
    except Exception as e:
        logger.error(f"Failed to create directory '{path}': {e}", exc_info=True)


def create_file(path, content=""):
    """
    Create a file if it doesn't exist.
    """
    try:
        logger.debug(f"Checking if file exists: {path}")
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Created file: {path}")
        else:
            logger.warning(f"File already exists: {path}")
    except Exception as e:
        logger.error(f"Failed to create file '{path}': {e}", exc_info=True)


def init_project(project_name):
    """
    Initialize a new Agent Actions project.
    """
    logger.info(f"Initializing project '{project_name}'")

    try:
        project_dir = os.path.join(os.getcwd(), project_name)
        config_dir = os.path.join(project_dir, 'agent_config')
        schema_dir = os.path.join(project_dir, 'schema')
        io_dir = os.path.join(project_dir, 'agent_io')
        config_file = os.path.join(project_dir, 'agent_actions.yml')

        # Creating main project directory
        logger.debug(f"Creating main project directory at {project_dir}")
        create_directory(project_dir)

        # Creating subdirectories
        logger.debug("Creating configuration, schema, and I/O directories")
        create_directory(config_dir)
        create_directory(schema_dir)
        create_directory(io_dir)

        # Creating Agent Actions configuration file
        logger.debug(f"Creating configuration file at {config_file}")
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

        logger.info(f"Project '{project_name}' initialized successfully.")

    except Exception as e:
        logger.critical(f"Failed to initialize project '{project_name}': {e}", exc_info=True)
