"""Agent workflow state management for execution status persistence."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AgentStateManager:
    """Manages agent execution state persistence and queries."""

    def __init__(self, status_file_path: Path, execution_order: list[str]):
        """Initialize state manager."""
        self.status_file = status_file_path
        self.execution_order = execution_order
        self.agent_status: dict[str, dict[str, Any]] = {}
        self._load_status()

    def _load_status(self):
        """Load agent status from file, or initialize with defaults."""
        if self.status_file.exists():
            try:
                with open(self.status_file, encoding="utf-8") as f:
                    self.agent_status = json.load(f)
                logger.info("Loaded status for %d agents", len(self.agent_status))
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.warning("Could not load status file: %s", e)
                self._initialize_default_status()
        else:
            self._initialize_default_status()

    def _initialize_default_status(self):
        """Initialize all agents with 'pending' status."""
        self.agent_status = {agent: {"status": "pending"} for agent in self.execution_order}

    def _save_status(self):
        """Persist current status to file."""
        try:
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(self.agent_status, f, indent=4)
        except (OSError, ValueError, TypeError) as e:
            logger.error("Error saving status: %s", e)

    def update_status(self, agent_name: str, status: str, **metadata):
        """Update agent status and persist to file."""
        if agent_name not in self.agent_status:
            self.agent_status[agent_name] = {}

        self.agent_status[agent_name]["status"] = status

        # Add any additional metadata
        for key, value in metadata.items():
            self.agent_status[agent_name][key] = value

        self._save_status()

    def get_status(self, agent_name: str) -> str:
        """Return current status of an agent, defaulting to 'pending'."""
        status: str = self.agent_status.get(agent_name, {}).get("status", "pending")
        return status

    def get_status_details(self, agent_name: str) -> dict[str, Any]:
        """Return full status details for an agent."""
        return self.agent_status.get(agent_name, {"status": "pending"})

    def is_completed(self, agent_name: str) -> bool:
        """Return True if agent is completed."""
        return self.get_status(agent_name) == "completed"

    def is_batch_submitted(self, agent_name: str) -> bool:
        """Return True if agent has batch jobs submitted."""
        return self.get_status(agent_name) == "batch_submitted"

    def is_failed(self, agent_name: str) -> bool:
        """Return True if agent has failed."""
        return self.get_status(agent_name) == "failed"

    def get_pending_agents(self, agents: list[str]) -> list[str]:
        """Return agents that are not yet completed."""
        return [agent for agent in agents if not self.is_completed(agent)]

    def get_batch_submitted_agents(self, agents: list[str]) -> list[str]:
        """Return agents with batch jobs submitted."""
        return [agent for agent in agents if self.is_batch_submitted(agent)]

    def get_failed_agents(self, agents: list[str]) -> list[str]:
        """Return agents that have failed."""
        return [agent for agent in agents if self.is_failed(agent)]

    def mark_running_as_failed(self):
        """Mark any agent in 'running' or 'checking_batch' status as failed."""
        for agent_name, details in self.agent_status.items():
            if details.get("status") in ["running", "checking_batch"]:
                self.update_status(agent_name, "failed")
                return agent_name
        return None

    def get_summary(self) -> dict[str, int]:
        """Return summary counts of agent statuses."""
        summary: dict[str, int] = {}
        for details in self.agent_status.values():
            status = details.get("status", "unknown")
            summary[status] = summary.get(status, 0) + 1
        return summary

    def is_workflow_complete(self) -> bool:
        """Return True if all agents have 'completed' status."""
        return all(details.get("status") == "completed" for details in self.agent_status.values())

    def has_any_failed(self) -> bool:
        """Return True if any agent has 'failed' status."""
        return any(details.get("status") == "failed" for details in self.agent_status.values())
