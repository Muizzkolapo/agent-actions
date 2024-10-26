import logging
import os

def setup_logging(log_file_path):
    # Create a logger
    logger = logging.getLogger('agent_actions')
    logger.setLevel(logging.DEBUG)

    # Create a file handler and set the logging level
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.DEBUG)

    # Create a console handler and set the logging level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)

    # Create a formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# Get the log file path
log_file_path = os.path.join(os.path.dirname(__file__), 'agent_actions.log')

# Set up the logger
logger = setup_logging(log_file_path)
