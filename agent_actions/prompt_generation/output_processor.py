"""Module for processing and combining output files."""

from agent_actions.prompt_generation.directory_handler import DirectoryCombiner


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
