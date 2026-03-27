import logging
import os
import shutil
from pathlib import Path

from agent_actions.errors import AgentNotFoundError
from agent_actions.utils.project_root import find_project_root

logger = logging.getLogger(__name__)


class AgentManager:
    """
    A class for managing agent directories and configurations.
    """

    @staticmethod
    def agent_exists(agent_name: str, project_root: Path | None = None) -> bool:
        """
        Check if an agent exists.

        Args:
            agent_name: Name of the agent to check.
            project_root: Optional project root to use instead of discovering from CWD.

        Returns:
            True if the agent exists, False otherwise.
        """
        try:
            agent_config_dir, _, _ = AgentManager.get_agent_paths(
                agent_name, project_root=project_root
            )
            return Path(agent_config_dir).exists()
        except AgentNotFoundError:
            return False

    @staticmethod
    def get_agent_paths(agent_name: str, project_root: Path | None = None) -> tuple[str, str, str]:
        """
        Construct and return key paths related to the agent.
        Searches for agent_actions.yml file to determine the project root,
        then looks for {agent_name}.yml to locate the agent directory.

        Args:
            agent_name: Name of the agent to find paths for
            project_root: Optional project root to use instead of discovering from CWD

        Returns:
            Tuple of (agent_config_dir, io_dir, logs_dir)

        Raises:
            AgentNotFoundError: If agent_actions.yml or agent configuration cannot be found
        """
        if project_root is None:
            project_root = find_project_root()
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
            logger.info("Cleaned directory %s for agent %s", directory, agent)
