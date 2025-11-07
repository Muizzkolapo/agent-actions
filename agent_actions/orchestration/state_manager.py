"""
Agent workflow state management module.

Handles loading, saving, and querying agent execution status.
Extracted from agent_workflow.py to reduce complexity.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from rich.console import Console


class AgentStateManager:
    """
    Manages agent execution state persistence and queries.

    Responsibilities:
    - Load/save agent status from/to .agent_status.json
    - Update individual agent status
    - Query agent statuses
    - Provide status summaries
    """

    def __init__(self, status_file_path: Path, execution_order: List[str]):
        """
        Initialize state manager.

        Args:
            status_file_path: Path to .agent_status.json
            execution_order: List of agent names in execution order
        """
        self.status_file = status_file_path
        self.execution_order = execution_order
        self.agent_status: Dict[str, Dict[str, Any]] = {}
        self.console = Console()
        self._load_status()

    def _load_status(self):
        """Load agent status from file, or initialize with defaults."""
        if self.status_file.exists():
            try:
                with open(self.status_file, 'r') as f:
                    self.agent_status = json.load(f)
                self.console.print(f'[dim]Loaded status for {len(self.agent_status)} agents[/dim]')
            except Exception as e:
                self.console.print(f'[yellow]Warning: Could not load status file: {e}[/yellow]')
                self._initialize_default_status()
        else:
            self._initialize_default_status()

    def _initialize_default_status(self):
        """Initialize all agents with 'pending' status."""
        self.agent_status = {
            agent: {'status': 'pending'}
            for agent in self.execution_order
        }

    def _save_status(self):
        """Persist current status to file."""
        try:
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.status_file, 'w') as f:
                json.dump(self.agent_status, f, indent=4)
        except Exception as e:
            self.console.print(f'[red]Error saving status: {e}[/red]')

    def update_status(self, agent_name: str, status: str, **metadata):
        """
        Update agent status and save to file.

        Args:
            agent_name: Name of the agent
            status: New status (pending|running|batch_submitted|checking_batch|completed|failed)
            **metadata: Additional metadata to store with status
        """
        if agent_name not in self.agent_status:
            self.agent_status[agent_name] = {}

        self.agent_status[agent_name]['status'] = status

        # Add any additional metadata
        for key, value in metadata.items():
            self.agent_status[agent_name][key] = value

        self._save_status()

    def get_status(self, agent_name: str) -> str:
        """
        Get current status of an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Status string, or 'pending' if not found
        """
        return self.agent_status.get(agent_name, {}).get('status', 'pending')

    def get_status_details(self, agent_name: str) -> Dict[str, Any]:
        """
        Get full status details for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Status details dictionary
        """
        return self.agent_status.get(agent_name, {'status': 'pending'})

    def is_completed(self, agent_name: str) -> bool:
        """Check if agent is completed."""
        return self.get_status(agent_name) == 'completed'

    def is_batch_submitted(self, agent_name: str) -> bool:
        """Check if agent has batch jobs submitted."""
        return self.get_status(agent_name) == 'batch_submitted'

    def is_failed(self, agent_name: str) -> bool:
        """Check if agent has failed."""
        return self.get_status(agent_name) == 'failed'

    def get_pending_agents(self, agents: List[str]) -> List[str]:
        """
        Get list of agents that are not completed.

        Args:
            agents: List of agent names to check

        Returns:
            List of agent names that are not completed
        """
        return [
            agent for agent in agents
            if not self.is_completed(agent)
        ]

    def get_batch_submitted_agents(self, agents: List[str]) -> List[str]:
        """
        Get list of agents with batch jobs submitted.

        Args:
            agents: List of agent names to check

        Returns:
            List of agent names with batch status
        """
        return [
            agent for agent in agents
            if self.is_batch_submitted(agent)
        ]

    def get_failed_agents(self, agents: List[str]) -> List[str]:
        """
        Get list of failed agents.

        Args:
            agents: List of agent names to check

        Returns:
            List of agent names that failed
        """
        return [
            agent for agent in agents
            if self.is_failed(agent)
        ]

    def mark_running_as_failed(self):
        """Mark any agent in 'running' or 'checking_batch' status as failed."""
        for agent_name, details in self.agent_status.items():
            if details.get('status') in ['running', 'checking_batch']:
                self.update_status(agent_name, 'failed')
                return agent_name
        return None

    def get_summary(self) -> Dict[str, int]:
        """
        Get summary counts of agent statuses.

        Returns:
            Dictionary with counts by status
        """
        summary = {}
        for details in self.agent_status.values():
            status = details.get('status', 'unknown')
            summary[status] = summary.get(status, 0) + 1
        return summary

    def is_workflow_complete(self) -> bool:
        """
        Check if all agents are completed.

        Returns:
            True if all agents have 'completed' status
        """
        return all(
            details.get('status') == 'completed'
            for details in self.agent_status.values()
        )

    def has_any_failed(self) -> bool:
        """
        Check if any agent has failed.

        Returns:
            True if any agent has 'failed' status
        """
        return any(
            details.get('status') == 'failed'
            for details in self.agent_status.values()
        )
