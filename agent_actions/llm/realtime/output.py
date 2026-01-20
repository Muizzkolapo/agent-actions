"""Module for handling output data saving operations."""

import json
from pathlib import Path
from agent_actions.output.file_writer import FileWriter
from agent_actions.errors import AgentActionsException  # New modular pattern!


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
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path
            self._ensure_directory_exists(str(output_file_path))
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(data)
        except IOError as e:
            raise AgentActionsException(
                "IOError saving main output",
                context={
                    "output_file_path": str(output_file_path),
                    "file_path": file_path,
                    "operation": "save_main_output",
                },
                cause=e,
            )
        except Exception as e:
            raise AgentActionsException(
                "Error saving main output",
                context={
                    "output_file_path": str(output_file_path),
                    "file_path": file_path,
                    "operation": "save_main_output",
                },
                cause=e,
            )

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
            relative_path = Path(file_path).relative_to(base_directory)
            side_output_dir = Path(output_directory).parent / "side_output"
            side_output_file_path = side_output_dir / relative_path.name
            self._ensure_directory_exists(str(side_output_file_path))
            existing_content = self._load_existing_content(str(side_output_file_path))
            existing_content.extend(data)
            with open(side_output_file_path, "w", encoding="utf-8") as file:
                json.dump(existing_content, file, indent=4)
        except IOError as e:
            raise AgentActionsException(
                "IOError saving side output",
                context={
                    "side_output_file_path": str(side_output_file_path),
                    "file_path": file_path,
                    "operation": "save_side_output",
                },
                cause=e,
            )
        except Exception as e:
            raise AgentActionsException(
                "Error saving side output",
                context={
                    "side_output_file_path": str(side_output_file_path),
                    "file_path": file_path,
                    "operation": "save_side_output",
                },
                cause=e,
            )

    def _ensure_directory_exists(self, file_path):
        """Ensure the directory for the file path exists."""
        directory = Path(file_path).parent
        directory.mkdir(parents=True, exist_ok=True)

    def _load_existing_content(self, file_path):
        """Load existing content from file if it exists."""
        if Path(file_path).exists():
            with open(file_path, "r", encoding="utf-8") as file:
                try:
                    existing_content = json.load(file)
                except json.JSONDecodeError:
                    existing_content = []
        else:
            existing_content = []
        if not isinstance(existing_content, list):
            existing_content = [existing_content]
        return existing_content
