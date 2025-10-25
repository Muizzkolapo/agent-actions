"""Module for processing and combining output files."""
import os
import json
from typing import List, Dict, Set


class FileHandler:
    """Handles file operations for the output processor."""

    @staticmethod
    def list_json_files(directory: str) -> Set[str]:
        """
        List all JSON files in a directory.
        
        Args:
            directory: Directory path to search
            
        Returns:
            Set of JSON filenames
        """
        return set([f for f in os.listdir(directory) if f.endswith('.json')])
    
    @staticmethod
    def read_json_file(file_path: str) -> List[Dict]:
        """
        Read JSON data from a file.
        
        Args:
            file_path: Path to the JSON file
            
        Returns:
            JSON data as a list of dictionaries
        """
        with open(file_path, 'r') as f:
            return json.load(f)
    
    @staticmethod
    def write_json_file(file_path: str, data: List[Dict]) -> None:
        """
        Write JSON data to a file.
        
        Args:
            file_path: Path to write the JSON file
            data: Data to write
        """
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    @staticmethod
    def ensure_directory(directory: str) -> None:
        """
        Ensure a directory exists, creating it if necessary.
        
        Args:
            directory: Directory path to create
        """
        os.makedirs(directory, exist_ok=True)




