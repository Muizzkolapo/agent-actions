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
from agent_actions.output.response.config_fields import get_default

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


class GuardStrategy(SkipStrategy):
    """Strategy for evaluating 'guard' with scope='action'."""

    def get_strategy_name(self) -> str:
        return "guard"

    def _handle_filter_error(
        self, agent_name: str, error_msg: str, passthrough_on_error: bool
    ) -> bool:
        """Handle filter evaluation errors."""
        logger.warning(
            "Guard evaluation error for %s: %s",
            agent_name,
            error_msg,
            extra={"action_name": agent_name, "operation": "guard_evaluation"},
        )

        if passthrough_on_error:
            logger.debug(
                "Action %s proceeding despite error (passthrough_on_error=True)",
                agent_name,
                extra={"action_name": agent_name, "passthrough_on_error": True},
            )
            return False

        fire_event(
            ActionSkipEvent(
                action_name=agent_name, skip_reason="error occurred and passthrough_on_error=False"
            )
        )
        return True

    def should_skip(self, agent_config: dict[str, Any], previous_outputs: dict[str, Any]) -> bool:
        """Evaluate action-level guard condition."""
        guard_config = agent_config.get("guard")

        if not guard_config or guard_config.get("scope") != "action":
            return False

        agent_name = agent_config["agent_type"]
        guard_clause = guard_config["clause"]
        passthrough_on_error = guard_config.get("passthrough_on_error", True)

        try:
            filter_service = get_global_guard_filter()

            prev = previous_outputs or {}
            context_data: dict[str, Any] = {
                "previous_outputs": prev,
                "agent_type": agent_config.get("agent_type"),
                "dependencies": agent_config.get("dependencies", []),
                "agent_config": {k: v for k, v in agent_config.items() if k != "guard"},
            }
            # Flatten action outputs to top-level so guards can use dot notation
            # e.g., assess_severity.severity != "low"
            for action_name, action_output in prev.items():
                # Skip internal metadata keys (e.g., "classify_meta")
                if action_name.endswith("_meta"):
                    continue
                if action_name in context_data:
                    logger.debug(
                        "Action '%s' collides with reserved context key — "
                        "use previous_outputs.%s in guard conditions",
                        action_name,
                        action_name,
                    )
                    continue
                # Unwrap single-item lists (common output_field pattern)
                if isinstance(action_output, list) and len(action_output) == 1:
                    context_data[action_name] = action_output[0]
                else:
                    context_data[action_name] = action_output

            # Promote output_field values to top-level (best-effort heuristic).
            # When a flattened action is a single-key dict, promote that key so
            # guards can write `severity != "low"` instead of `assess_severity.severity`.
            for key in list(context_data.keys()):
                val = context_data[key]
                if isinstance(val, dict) and len(val) == 1:
                    field_name, field_value = next(iter(val.items()))
                    if field_name not in context_data:
                        context_data[field_name] = field_value

            logger.debug(
                "Evaluating action-level guard for %s",
                agent_name,
                extra={
                    "action_name": agent_name,
                    "guard": guard_clause,
                    "operation": "guard_evaluation",
                },
            )

            filter_result = filter_service.filter_item(
                FilterItemRequest(
                    data=context_data,
                    condition=guard_clause,
                    timeout=agent_config.get(
                        "max_execution_time", get_default("max_execution_time")
                    ),
                )
            )

            if not filter_result.success:
                error_msg = filter_result.error or "Unknown filter error"
                return self._handle_filter_error(agent_name, error_msg, passthrough_on_error)

            # Handle filter result
            if not filter_result.matched:
                fire_event(
                    ActionSkipEvent(action_name=agent_name, skip_reason="guard condition not met")
                )
                logger.debug(
                    "Guard details: %s",
                    guard_clause,
                    extra={
                        "action_name": agent_name,
                        "guard": guard_clause,
                        "context_data": context_data,
                        "operation": "guard_evaluation",
                    },
                )
                return True

            return False

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            return self._handle_filter_error(agent_name, str(e), passthrough_on_error)


class LegacySkipIfStrategy(SkipStrategy):
    """Strategy for evaluating legacy 'skip_if' field."""

    def get_strategy_name(self) -> str:
        return "skip_if (legacy)"

    def should_skip(self, agent_config: dict[str, Any], previous_outputs: dict[str, Any]) -> bool:
        """Evaluate legacy skip_if condition using modern WHERE filter."""
        skip_if = agent_config.get("skip_if")
        if not skip_if:
            return False

        agent_name = agent_config["agent_type"]

        try:
            context = {"previous_outputs": previous_outputs or {}, "agent_config": agent_config}

            # Use modern guard filter - skip_if expression evaluated as guard condition
            filter_service = get_global_guard_filter()
            request = FilterItemRequest(data=context, condition=skip_if)
            filter_result = filter_service.filter_item(request)

            # If evaluation failed, don't skip (fail-open)
            if not filter_result.success:
                logger.debug(
                    "Legacy skip_if evaluation failed for %s: %s", agent_name, filter_result.error
                )
                return False

            # Skip if expression matched (direct logic - different from skip_condition)
            should_skip = filter_result.matched

            if should_skip:
                fire_event(
                    ActionSkipEvent(
                        action_name=agent_name, skip_reason="legacy skip_if condition matched"
                    )
                )

            return should_skip

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.warning(
                "Error evaluating legacy skip_if condition for %s: %s",
                agent_name,
                e,
                exc_info=True,
                extra={
                    "action_name": agent_name,
                    "skip_if": skip_if,
                    "operation": "legacy_skip_if_evaluation",
                },
            )
            return False  # Don't skip on error


class SkipEvaluator:
    """Orchestrates skip condition evaluation in precedence order."""

    def __init__(self, console: Console | None = None):
        """Initialize skip evaluator with strategies."""
        self.console = console or Console()
        self.strategies = [
            SkipConditionStrategy(self.console),
            GuardStrategy(self.console),
            LegacySkipIfStrategy(self.console),
        ]

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
