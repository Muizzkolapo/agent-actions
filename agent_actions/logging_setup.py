import logging
import os


def setup_logging(log_file='logs/agent_actions.log', level=logging.INFO):
    project_root = os.getcwd()
    # Ensure the logs directory exists
    log_file_path = os.path.join(project_root, log_file)
    logs_dir = os.path.dirname(log_file_path)
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # Create the logger if not already configured
    logger = logging.getLogger('agent_actions')
    logger.setLevel(level)
    
    # Avoid adding duplicate handlers
    if not logger.hasHandlers():
        # Set up console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        
        # Set up file handler
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(level)
        
        # Define a common log format
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        # Add both handlers to the logger
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    
    return logger
