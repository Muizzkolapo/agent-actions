import json
import shutil
from typing import Callable, Optional, Dict, Any
from agent_actions.io.file_handler import FileHandler
from pathlib import Path
from agent_actions.errors import AgentNotFoundError  # New modular pattern!
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class AgentManager:
    """
    A class for managing agent directories and configurations.
    """

    @staticmethod
    def find_project_root(
        start_path: Path, marker_file: str = "agent_actions.yml"
    ) -> Optional[Path]:
        """
        Find the project root directory by searching for a marker file.

        Args:
            start_path: Path to start searching from
            marker_file: Name of the file that marks the project root (default: 'agent_actions.yml')

        Returns:
            Path to project root if found, None otherwise
        """
        current = Path(start_path).resolve()
        while current != current.parent:
            if (current / marker_file).exists():
                return current
            current = current.parent
        return None

    @staticmethod
    def clean_agent_directories(agent_name: str) -> bool:
        """
        Deletes all files under the source and target folders for the specified agent.

        Args:
            agent_name: Name of the agent whose directories should be cleaned

        Returns:
            bool: True if directories were successfully cleaned, False otherwise
        """
        current_dir = Path.cwd()
        agent_folder = FileHandler.find_specific_folder(str(current_dir), agent_name, "agent_io")
        if agent_folder is None:
            print(f"Agent folder not found for agent: {agent_name}")
            return False
        source_dir = Path(agent_folder) / "source"
        target_dir = Path(agent_folder) / "target"
        for directory in [source_dir, target_dir]:
            if directory.exists():
                shutil.rmtree(directory)
                print(f"Deleted directory: {directory}")
            else:
                print(f"Directory not found: {directory}")
        return True

    @staticmethod
    def clean_agent_output(agent_name: str, agent_type: str, function_name: str) -> int:
        """
        Cleans the agent output by applying a specified function to each JSON file
        in the target directory of the agent.

        Args:
            agent_name: Name of the agent
            agent_type: Type of the agent
            function_name: Name of the function to apply to the JSON data

        Returns:
            int: Number of files successfully processed
        """
        project_root = Path.cwd()
        input_directory = project_root / "agent_io" / agent_name / "target" / agent_type
        function_call: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = globals().get(
            function_name
        )
        processed_count = 0
        if function_call and callable(function_call):
            for root, _, files in os.walk(str(input_directory)):
                for file_name in files:
                    if file_name.endswith(".json"):
                        file_path = Path(root) / file_name
                        try:
                            with open(file_path, "r", encoding="utf-8") as file:
                                data = json.load(file)
                            processed_data = function_call(data)
                            with open(file_path, "w", encoding="utf-8") as file:
                                json.dump(processed_data, file, indent=4)
                            processed_count += 1
                        except (json.JSONDecodeError, IOError) as e:
                            print(f"Error processing file {file_path}: {str(e)}")
        return processed_count

    @staticmethod
    def agent_exists(agent_name: str) -> bool:
        """
        Check if an agent exists.

        Args:
            agent_name: Name of the agent to check.

        Returns:
            True if the agent exists, False otherwise.
        """
        try:
            agent_config_dir, _, _ = self.get_agent_paths(agent_name)
            return Path(agent_config_dir).exists()
        except AgentNotFoundError:
            return False

    @staticmethod
    def get_agent_paths(agent_name: str) -> tuple[str, str, str]:
        """
        Construct and return key paths related to the agent.
        Searches for agent_actions.yml file to determine the project root,
        then looks for {agent_name}.yml to locate the agent directory.

        Args:
            agent_name: Name of the agent to find paths for

        Returns:
            Tuple of (agent_config_dir, io_dir, logs_dir)

        Raises:
            AgentNotFoundError: If agent_actions.yml or agent configuration cannot be found
        """
        project_root = AgentManager.find_project_root(Path.cwd())
        if not project_root:
            raise AgentNotFoundError(
                "Could not find agent_actions.yml in current or parent directories",
                context={"current_directory": str(Path.cwd()), "marker_file": "agent_actions.yml"},
            )
        agent_yml = f"{agent_name}.yml"
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if "rendered_workflow" not in d]
            if agent_yml in files:
                base_dir = Path(root).parent
                agent_config_dir = base_dir / "agent_config"
                io_dir = base_dir / "agent_io"
                logs_dir = base_dir / "logs"
                return (str(agent_config_dir), str(io_dir), str(logs_dir))
        raise AgentNotFoundError(
            "Could not find configuration for agent",
            context={
                "agent_name": agent_name,
                "project_root": str(project_root),
                "expected_file": f"{agent_name}.yml",
            },
        )

    @classmethod
    def clean_directory(cls, agent: str, directory: Path) -> None:
        """Clean a specific directory for an agent."""
        if directory.exists():
            shutil.rmtree(directory)
            logger.info("Cleaned directory {directory} for agent %s", agent)
