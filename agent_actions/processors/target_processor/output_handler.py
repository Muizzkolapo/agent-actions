"""Module for handling output data saving operations."""
import json
import os
from agent_actions.handlers.file_writer import FileWriter
from agent_actions.cli.exceptions import AgentActionsError


class OutputHandler:
    """Responsible for saving output data to appropriate locations."""
    
    def save_main_output(self, data, file_path, base_directory, output_directory):
        """
        Save main output data to the output directory.
        
        Args:
            data: Data to save
            file_path: Path to the input file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be saved
        """
        try:
            relative_path = os.path.relpath(file_path, base_directory)
            output_file_path = os.path.join(output_directory, relative_path)
            self._ensure_directory_exists(output_file_path)
            
            file_writer = FileWriter(output_file_path)
            file_writer.write_target(data)
        except IOError as e:
            raise AgentActionsError(f"IOError saving main output to {output_file_path}: {str(e)}") from e
        except Exception as e:
            raise AgentActionsError(f"Error saving main output to {output_file_path}: {str(e)}") from e
    
    def save_side_output(self, data, file_path, base_directory, output_directory):
        """
        Save side output data to the side_output directory.
        
        Args:
            data: Side output data to save
            file_path: Path to the input file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the main output is saved
        """
        try:
            relative_path = os.path.relpath(file_path, base_directory)
            side_output_dir = os.path.join(os.path.dirname(output_directory), 'side_output')
            side_output_file_path = os.path.join(side_output_dir, os.path.basename(relative_path))
            self._ensure_directory_exists(side_output_file_path)
            
            # Load existing content if available
            existing_content = self._load_existing_content(side_output_file_path)
            
            # Merge and save content
            existing_content.extend(data)
            with open(side_output_file_path, 'w', encoding='utf-8') as file:
                json.dump(existing_content, file, indent=4)
        except IOError as e:
            raise AgentActionsError(f"IOError saving side output to {side_output_file_path}: {str(e)}") from e
        except Exception as e:
            raise AgentActionsError(f"Error saving side output to {side_output_file_path}: {str(e)}") from e
    
    def _ensure_directory_exists(self, file_path):
        """Ensure the directory for the file path exists."""
        directory = os.path.dirname(file_path)
        os.makedirs(directory, exist_ok=True)
    
    def _load_existing_content(self, file_path):
        """Load existing content from file if it exists."""
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                try:
                    existing_content = json.load(file)
                except json.JSONDecodeError:
                    existing_content = []
        else:
            existing_content = []
        
        # Ensure content is a list
        if not isinstance(existing_content, list):
            existing_content = [existing_content]
        
        return existing_content