from pathlib import Path
from typing import Set
from agent_actions.prompt_generation.json_file_handler import JsonFileHandler

class DirectoryCombiner:
    """Handles combining JSON data from directories."""

    def __init__(self):
        """Initialize the directory combiner."""
        self.file_handler = FileHandler()

    def combine_directories(self, dir_1: str, dir_2: str, output_dir: str) -> None:
        """
        Combine JSON files from two directories into an output directory.
        
        Args:
            dir_1: First directory path
            dir_2: Second directory path
            output_dir: Output directory path
        """
        self.file_handler.ensure_directory(output_dir)
        files_dir_1 = self.file_handler.list_json_files(dir_1)
        files_dir_2 = self.file_handler.list_json_files(dir_2)
        common_files = files_dir_1.intersection(files_dir_2)
        files_only_in_dir_1 = files_dir_1 - common_files
        files_only_in_dir_2 = files_dir_2 - common_files
        self._combine_common_files(dir_1, dir_2, output_dir, common_files)
        self._copy_unique_files(dir_1, output_dir, files_only_in_dir_1, 'dir_1')
        self._copy_unique_files(dir_2, output_dir, files_only_in_dir_2, 'dir_2')

    def _combine_common_files(self, dir_1: str, dir_2: str, output_dir: str, common_files: Set[str]) -> None:
        """
        Combine files that exist in both directories.
        
        Args:
            dir_1: First directory path
            dir_2: Second directory path
            output_dir: Output directory path
            common_files: Set of filenames common to both directories
        """
        for filename in common_files:
            file_path_1 = Path(dir_1) / filename
            file_path_2 = Path(dir_2) / filename
            data1 = self.file_handler.read_json_file(str(file_path_1))
            data2 = self.file_handler.read_json_file(str(file_path_2))
            combined_data = data1 + data2
            output_path = Path(output_dir) / filename
            self.file_handler.write_json_file(str(output_path), combined_data)

    def _copy_unique_files(self, source_dir: str, output_dir: str, unique_files: Set[str], dir_name: str) -> None:
        """
        Copy files that only exist in one directory.
        
        Args:
            source_dir: Source directory path
            output_dir: Output directory path
            unique_files: Set of filenames unique to the source directory
            dir_name: Name of the source directory for logging
        """
        for filename in unique_files:
            file_path = Path(source_dir) / filename
            data = self.file_handler.read_json_file(str(file_path))
            output_path = Path(output_dir) / filename
            self.file_handler.write_json_file(str(output_path), data)
            print(f'Copied {filename} from {dir_name} to {output_path}')