import json
import os

class StateManager:
    def __init__(self, state_file='agent_state.json', state_dir=None):
        # Determine the state directory
        if state_dir is None:
            # Default to a hidden directory in the current working directory
            home_dir = os.getcwd()  # Change this line to use the current working directory
            state_dir = os.path.join(home_dir, 'project_state', 'state')
        self.state_dir = state_dir
        
        # Ensure the state directory exists
        os.makedirs(self.state_dir, exist_ok=True)
        
        # Full path to the state file
        self.state_file = os.path.join(self.state_dir, state_file)
        
        # Debugging: Print where the state file is stored
        print(f"State file will be stored at: {self.state_file}")

    def save_state(self, state):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
            print(f"State saved to {self.state_file}")
        except Exception as e:
            print(f"Failed to save state: {e}")

    def load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                print(f"State loaded from {self.state_file}")
                return state
            else:
                print("No existing state file found.")
        except Exception as e:
            print(f"Failed to load state: {e}")
        return None

    def clear_state(self):
        try:
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
                print(f"State file {self.state_file} cleared.")
        except Exception as e:
            print(f"Failed to clear state: {e}")
