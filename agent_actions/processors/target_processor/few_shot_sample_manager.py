"""Module for managing few-shot samples."""

from typing import Dict
import logging

from agent_actions.handlers.file_handler import FileHandler
from agent_actions.handlers.prompt_handler import PromptLoader

from .interfaces import IFewShotSampleManager

logger = logging.getLogger(__name__)


class FewShotSampleManager(IFewShotSampleManager):
    """Handles few-shot sample management (Single Responsibility)."""

    def __init__(self, agent_config: Dict, agent_name: str):
        """
        Initialize the few-shot sample manager.

        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name

    def add_few_shot_samples(self, contents: Dict) -> Dict:
        """
        Add few-shot samples to content if configured.

        Args:
            contents: Content to add samples to

        Returns:
            Content with added samples if applicable

        Raises:
            ValueError: If samples cannot be added to content
        """
        sample_count = self._parse_sample_count()
        if sample_count > 0:
            try:
                agent_id = self.agent_config.get("agent_type", self.agent_name)
                _, _, few_shot_samples_path = FileHandler.get_agent_paths(agent_id)
                if not few_shot_samples_path:
                    logger.warning(
                        "Few shot samples directory not found for agent '%s'. Skipping few-shot enrichment.",
                        agent_id,
                    )
                    return contents

                samples = PromptLoader.load_few_shot_samples(
                    few_shot_samples_path,
                    self.agent_config["agent_type"],
                    sample_count,
                )
                if isinstance(contents, dict):
                    contents["samples"] = samples
                else:
                    raise TypeError("Content must be a dictionary to add samples")
            except Exception as e:
                raise ValueError(f"Failed to add few-shot samples: {str(e)}")

        return contents

    def _parse_sample_count(self) -> int:
        """
        Parse the sample count from agent configuration.

        Returns:
            Number of samples to use
        """
        try:
            return int(self.agent_config.get("use_few_shot_samples", 0))
        except ValueError:
            return 0
