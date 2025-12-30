"""Module for processing and combining output files."""

from pathlib import Path
from typing import List, Dict, Optional
from agent_actions.prompt_generation.directory_handler import DirectoryCombiner
from agent_actions.prompt_generation.json_file_handler import JsonFileHandler


class OutputProcessor:
    """Processes output data from workflow runs."""

    def __init__(self, parent_output, constructor_path):
        """
        Initialize the output processor.

        Args:
            parent_output: Parent output object
            constructor_path: Path to the constructor
        """
        self.parent_output = parent_output
        self.constructor_path = constructor_path
        self.failed = False
        self.directory_combiner = DirectoryCombiner()

    def combine_json_arrays(self, dir_1: str, dir_2: str, output_dir: str) -> None:
        """
        Combine JSON arrays from two directories.

        Args:
            dir_1: First directory path
            dir_2: Second directory path
            output_dir: Output directory path
        """
        self.directory_combiner.combine_directories(dir_1, dir_2, output_dir)

    def process_final_output(self, ephemeral_directories: List[Dict]) -> Optional[str]:
        """
        Process the final output from a workflow run.

        Args:
            ephemeral_directories: List of dictionaries containing ephemeral directory information

        Returns:
            Path to the final workflow output directory, or None if no ephemeral directories
        """
        if not ephemeral_directories:
            return None
        final_agent_output_folder = ephemeral_directories[-1]["output_folder"]
        final_workflow_output = Path(final_agent_output_folder).parent / "final_workflow_output"
        JsonFileHandler.ensure_directory(str(final_workflow_output))
        side_output_dir = Path(final_agent_output_folder).parent / "side_output"
        if side_output_dir.exists():
            self.combine_json_arrays(
                final_agent_output_folder, str(side_output_dir), str(final_workflow_output)
            )
        return str(final_workflow_output)
