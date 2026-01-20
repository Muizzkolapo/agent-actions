"""
Agent skip condition evaluation module.

Implements strategy pattern for different skip condition types.
Extracted from agent_workflow.py to reduce _should_skip_agent() complexity (CC 20 → <5).
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from rich.console import Console

from agent_actions.processing.guards.filter import (
    get_global_guard_filter,
    FilterItemRequest,
)

logger = logging.getLogger(__name__)


class SkipStrategy(ABC):
    """Base strategy for evaluating skip conditions."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    @abstractmethod
    def should_skip(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any]) -> bool:
        """
        Determine if agent should be skipped.

        Args:
            agent_config: Agent configuration
            previous_outputs: Previous agent outputs

        Returns:
            True if agent should be skipped, False otherwise
        """

    @abstractmethod
    def get_strategy_name(self) -> str:
        """Get name of this strategy for logging."""


class SkipConditionStrategy(SkipStrategy):
    """Strategy for evaluating 'skip_condition' field."""

    def get_strategy_name(self) -> str:
        return "skip_condition"

    def should_skip(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any]) -> bool:
        """Evaluate skip_condition using modern WHERE filter."""
        skip_condition = agent_config.get("skip_condition")
        if not skip_condition:
            return False

        agent_name = agent_config.get("agent_type", "unknown")

        try:
            context = {"previous_outputs": previous_outputs or {}, "agent_config": agent_config}

            # Extract WHERE clause from skip_condition config
            where_clause = None
            if isinstance(skip_condition, dict) and "where" in skip_condition:
                where_clause = skip_condition["where"]
            elif isinstance(skip_condition, str):
                where_clause = skip_condition

            if not where_clause:
                return False

            # Use modern guard filter - skip if condition NOT matched
            filter_service = get_global_guard_filter()
            request = FilterItemRequest(data=context, condition=where_clause)
            filter_result = filter_service.filter_item(request)

            # If evaluation failed, don't skip (fail-open)
            if not filter_result.success:
                logger.debug(
                    "Skip condition evaluation failed for %s: %s", agent_name, filter_result.error
                )
                return False

            # Skip if condition NOT matched (inverse logic)
            should_skip = not filter_result.matched

            if should_skip:
                self.console.print(
                    f"[yellow]🔍 Agent {agent_name} SKIPPED: "
                    f"skip_condition evaluated to True[/yellow]"
                )
            else:
                self.console.print(
                    f"[green]✓ Agent {agent_name} passed skip_condition check[/green]"
                )

            return should_skip

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.warning(
                "Error evaluating skip condition for %s: %s",
                agent_name,
                e,
                exc_info=True,
                extra={"agent_name": agent_name, "operation": "skip_condition_evaluation"},
            )
            return False  # Don't skip on error


class GuardStrategy(SkipStrategy):
    """Strategy for evaluating 'guard' with scope='agent'."""

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
            extra={"agent_name": agent_name, "operation": "guard_evaluation"},
        )

        if passthrough_on_error:
            logger.debug(
                "Agent %s proceeding despite error (passthrough_on_error=True)",
                agent_name,
                extra={"agent_name": agent_name, "passthrough_on_error": True},
            )
            return False

        self.console.print(
            f"[red]→ Agent {agent_name} SKIPPED due to error and passthrough_on_error=False[/red]"
        )
        return True

    def should_skip(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any]) -> bool:
        """Evaluate agent-level guard condition."""
        guard_config = agent_config.get("guard")

        # Only handle agent-scope guards
        if not guard_config or guard_config.get("scope") != "agent":
            return False

        agent_name = agent_config.get("agent_type", "unknown")
        guard_clause = guard_config["clause"]
        passthrough_on_error = guard_config.get("passthrough_on_error", True)

        try:
            filter_service = get_global_guard_filter()

            context_data = {
                "previous_outputs": previous_outputs or {},
                "agent_type": agent_config.get("agent_type"),
                "dependencies": agent_config.get("dependencies", []),
                "agent_config": {k: v for k, v in agent_config.items() if k not in ["guard"]},
            }

            logger.debug(
                "Evaluating agent-level guard for %s",
                agent_name,
                extra={
                    "agent_name": agent_name,
                    "guard": guard_clause,
                    "operation": "guard_evaluation",
                },
            )

            filter_result = filter_service.filter_item(
                FilterItemRequest(
                    data=context_data,
                    condition=guard_clause,
                    timeout=agent_config.get("max_execution_time", 5),
                )
            )

            # Handle filter execution errors
            if not filter_result.success:
                error_msg = filter_result.error or "Unknown filter error"
                return self._handle_filter_error(agent_name, error_msg, passthrough_on_error)

            # Handle filter result
            if not filter_result.matched:
                self.console.print(
                    f"[yellow]🚫 Agent {agent_name} SKIPPED: guard condition not met[/yellow]"
                )
                logger.debug(
                    "Guard details: %s",
                    guard_clause,
                    extra={
                        "agent_name": agent_name,
                        "guard": guard_clause,
                        "context_data": context_data,
                        "operation": "guard_evaluation",
                    },
                )
                return True

            exec_time = filter_result.execution_time
            self.console.print(
                f"[green]✓ Agent {agent_name} passed guard check "
                f"(execution time: {exec_time:.3f}s)[/green]"
            )
            return False

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            return self._handle_filter_error(agent_name, str(e), passthrough_on_error)


class LegacySkipIfStrategy(SkipStrategy):
    """Strategy for evaluating legacy 'skip_if' field."""

    def get_strategy_name(self) -> str:
        return "skip_if (legacy)"

    def should_skip(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any]) -> bool:
        """Evaluate legacy skip_if condition using modern WHERE filter."""
        skip_if = agent_config.get("skip_if")
        if not skip_if:
            return False

        agent_name = agent_config.get("agent_type", "unknown")

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
                self.console.print(
                    f"[yellow]🔍 Agent {agent_name} SKIPPED: legacy skip_if condition[/yellow]"
                )
            else:
                self.console.print(
                    f"[green]✓ Agent {agent_name} passed legacy skip_if check[/green]"
                )

            return should_skip

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.warning(
                "Error evaluating legacy skip_if condition for %s: %s",
                agent_name,
                e,
                exc_info=True,
                extra={
                    "agent_name": agent_name,
                    "skip_if": skip_if,
                    "operation": "legacy_skip_if_evaluation",
                },
            )
            return False  # Don't skip on error


class SkipEvaluator:
    """
    Orchestrates skip condition evaluation using strategy pattern.

    Evaluates skip conditions in order of precedence:
    1. skip_condition
    2. guard (scope=agent)
    3. skip_if (legacy)
    """

    def __init__(self, console: Optional[Console] = None):
        """
        Initialize skip evaluator with strategies.

        Args:
            console: Rich console for output
        """
        self.console = console or Console()
        self.strategies = [
            SkipConditionStrategy(self.console),
            GuardStrategy(self.console),
            LegacySkipIfStrategy(self.console),
        ]

    def __repr__(self):
        """Return string representation."""
        return f"SkipEvaluator(strategies={len(self.strategies)})"

    def should_skip_agent(
        self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any] = None
    ) -> bool:
        """
        Determine if an agent should be skipped based on skip conditions.

        Evaluates all skip strategies in order.
        Returns True at first skip condition that matches.

        Args:
            agent_config: Agent configuration
            previous_outputs: Previous agent outputs for context

        Returns:
            True if the agent should be skipped, False otherwise
        """
        previous_outputs = previous_outputs or {}

        for strategy in self.strategies:
            try:
                if strategy.should_skip(agent_config, previous_outputs):
                    return True
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                agent_name = agent_config.get("agent_type", "unknown")
                logger.exception(
                    "Unexpected error in skip strategy %s for %s: %s",
                    strategy.get_strategy_name(),
                    agent_name,
                    e,
                    extra={
                        "agent_name": agent_name,
                        "strategy_name": strategy.get_strategy_name(),
                        "operation": "skip_strategy_evaluation",
                    },
                )
                # Continue to next strategy on error

        return False  # No strategy indicated skip
