"""Action skip condition evaluation using strategy pattern."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)


class SkipStrategy(ABC):
    """Base strategy for evaluating skip conditions."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    @abstractmethod
    def should_skip(self, agent_config: dict[str, Any], previous_outputs: dict[str, Any]) -> bool:
        """Return True if the agent should be skipped."""

    @abstractmethod
    def get_strategy_name(self) -> str:
        """Return name of this strategy for logging."""


class SkipEvaluator:
    """Orchestrates skip condition evaluation in precedence order."""

    def __init__(self, console: Console | None = None):
        """Initialize skip evaluator with strategies."""
        self.console = console or Console()
        # No strategy is registered: the only one read skip_condition, which no workflow
        # can set any more. A guard skips records.
        self.strategies: list[SkipStrategy] = []

    def __repr__(self):
        return f"SkipEvaluator(strategies={len(self.strategies)})"

    def should_skip_action(
        self, agent_config: dict[str, Any], previous_outputs: dict[str, Any] | None = None
    ) -> bool:
        """
        Determine if an action should be skipped based on skip conditions.

        Evaluates all skip strategies in order.
        Returns True at first skip condition that matches.

        Args:
            agent_config: Action configuration
            previous_outputs: Previous action outputs for context

        Returns:
            True if the action should be skipped, False otherwise
        """
        previous_outputs = previous_outputs or {}

        for strategy in self.strategies:
            try:
                if strategy.should_skip(agent_config, previous_outputs):
                    return True
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                agent_name = agent_config.get("agent_type") or "NOT_SET"
                logger.exception(
                    "Unexpected error in skip strategy %s for %s: %s",
                    strategy.get_strategy_name(),
                    agent_name,
                    e,
                    extra={
                        "action_name": agent_name,
                        "strategy_name": strategy.get_strategy_name(),
                        "operation": "skip_strategy_evaluation",
                    },
                )
                # Continue to next strategy on error

        return False  # No strategy indicated skip
