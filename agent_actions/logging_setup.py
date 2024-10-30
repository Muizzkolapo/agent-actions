import logging
import os

def setup_logging(log_file_path):
    # Create a logger
    logger = logging.getLogger('agent_actions')
    logger.setLevel(logging.DEBUG)

    # Create a file handler for detailed logging
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)

    # Create a console handler for minimal output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)  # Only show warnings and errors
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Suppress other loggers
    logging.getLogger('sagemaker').setLevel(logging.WARNING)
    
    # Prevent logs from propagating to parent loggers
    logger.propagate = False

    return logger

# Get the log file path
log_file_path = os.path.join(os.path.dirname(__file__), 'agent_actions.log')

# Set up the logger
logger = setup_logging(log_file_path)
