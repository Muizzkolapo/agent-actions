import os
import pickle
import logging

logger = logging.getLogger(__name__)

def save_checkpoint(state, checkpoint_file='checkpoint.pkl', folder='project_state'):
    """
    Save the current state to a checkpoint file in a specified folder.
    """
    try:
        if not os.path.exists(folder):
            os.makedirs(folder)
        checkpoint_path = os.path.join(folder, checkpoint_file)
        with open(checkpoint_path, 'wb') as f:
            pickle.dump(state, f)
        logger.info(f"Checkpoint saved to {checkpoint_path}")
    except Exception as e:
        logger.error(f"Failed to save checkpoint: {e}")

def load_checkpoint(checkpoint_file='checkpoint.pkl', folder='project_state'):
    """
    Load the state from a checkpoint file in a specified folder.
    """
    checkpoint_path = os.path.join(folder, checkpoint_file)
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, 'rb') as f:
                state = pickle.load(f)
            logger.info(f"Checkpoint loaded from {checkpoint_path}")
            return state
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            return None
    else:
        logger.info("No checkpoint file found. Starting fresh.")
        return None

def remove_checkpoint(checkpoint_file='checkpoint.pkl', folder='project_state'):
    """
    Remove the checkpoint file from a specified folder after successful completion.
    """
    try:
        checkpoint_path = os.path.join(folder, checkpoint_file)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)
            logger.info(f"Checkpoint file {checkpoint_path} removed after successful execution.")
    except Exception as e:
        logger.error(f"Failed to remove checkpoint file: {e}")
