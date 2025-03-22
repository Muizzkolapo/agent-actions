"""
Agent runner service.
"""

from pathlib import Path
from typing import Optional
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.workflow.agent_workflow import AgentWorkflow


class AgentRunnerService:
    """Service for running agents."""
    
    @staticmethod
    def find_config_file(agent_config_dir: Path, filename: str) -> Optional[Path]:
        """
        Find the configuration file path.

        Args:
            agent_config_dir: Directory containing agent configurations.
            filename: Configuration filename.

        Returns:
            Path to the configuration file if found, None otherwise.
        """
        full_path_str = FileHandler.find_config_file(str(agent_config_dir), filename)
        return Path(full_path_str) if full_path_str else None

    @staticmethod
    def run_agent_workflow(
        agent_name: str,
        full_path: Path,
        default_config_path: Path,
        user_code: Optional[str],
        parent_pipeline: Optional[str]
    ) -> None:
        """
        Run the agent workflow.

        Args:
            agent_name: Name of the agent.
            full_path: Path to the agent configuration file.
            default_config_path: Path to the default configuration file.
            user_code: Path to user-defined functions directory.
            parent_pipeline: Name of the parent pipeline.
        """
        use_tools = user_code is not None
        
        workflow = AgentWorkflow(
            constructor_path=str(full_path),
            user_code_path=user_code,
            default_path=str(default_config_path),
            use_tools=use_tools,
            parent_pipeline=parent_pipeline
        )
        workflow.run()