import logging
import os

def setup_logging(log_file='logs/agent_actions.log', log_level=logging.INFO):
    # Determine the user's current working directory (project root)
    project_root = os.getcwd()

    # Define the full path for the log file within the user's project
    log_file_path = os.path.join(project_root, log_file)

    # Create the logs directory if it doesn't exist
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    # Define the logging format
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Set up the logging configuration
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.FileHandler(log_file_path),  # Log to file in user's project
            logging.StreamHandler()              # Also log to console
        ]
    )

    # Create and return the logger
    logger = logging.getLogger('agent_actions')
    return logger

# Initialize the logger
logger = setup_logging()
