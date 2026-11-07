"""Action skip condition evaluation using strategy pattern."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from rich.console import Console

from agent_actions.input.preprocessing.filtering.guard_filter import (
    FilterItemRequest,
    get_global_guard_filter,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import ActionSkipEvent

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


class SkipConditionStrategy(SkipStrategy):
    """Strategy for evaluating 'skip_condition' field."""

    def get_strategy_name(self) -> str:
        return "skip_condition"

    def should_skip(self, agent_config: dict[str, Any], previous_outputs: dict[str, Any]) -> bool:
        """Evaluate skip_condition using modern WHERE filter."""
        skip_condition = agent_config.get("skip_condition")
        if not skip_condition:
            return False

        agent_name = agent_config["agent_type"]

        try:
            context = {"previous_outputs": previous_outputs or {}, "agent_config": agent_config}

            where_clause = None
            if isinstance(skip_condition, dict) and "where" in skip_condition:
                where_clause = skip_condition["where"]
            elif isinstance(skip_condition, str):
                where_clause = skip_condition

            if not where_clause:
                return False

            filter_service = get_global_guard_filter()
            request = FilterItemRequest(data=context, condition=where_clause)
            filter_result = filter_service.filter_item(request)

            if not filter_result.success:
                logger.debug(
                    "Skip condition evaluation failed for %s: %s", agent_name, filter_result.error
                )
                return False

            # Inverse logic: skip when condition is NOT matched
            should_skip = not filter_result.matched

            if should_skip:
                fire_event(
                    ActionSkipEvent(
                        action_name=agent_name, skip_reason="skip_condition evaluated to True"
                    )
                )

            return should_skip

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.warning(
                "Error evaluating skip condition for %s: %s",
                agent_name,
                e,
                exc_info=True,
                extra={"action_name": agent_name, "operation": "skip_condition_evaluation"},
            )
            return False  # Don't skip on error


class SkipEvaluator:
    """Orchestrates skip condition evaluation in precedence order."""

    def __init__(self, console: Console | None = None):
        """Initialize skip evaluator with strategies."""
        self.console = console or Console()
        self.strategies = [SkipConditionStrategy(self.console)]

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
