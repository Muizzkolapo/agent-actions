"""
Agent skip condition evaluation module.

Implements strategy pattern for different skip condition types.
Extracted from agent_workflow.py to reduce _should_skip_agent() complexity (CC 20 → <5).
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from rich.console import Console

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
        pass

    @abstractmethod
    def get_strategy_name(self) -> str:
        """Get name of this strategy for logging."""
        pass


class SkipConditionStrategy(SkipStrategy):
    """Strategy for evaluating 'skip_condition' field."""

    def get_strategy_name(self) -> str:
        return "skip_condition"

    def should_skip(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any]) -> bool:
        """Evaluate skip_condition using safe evaluation."""
        skip_condition = agent_config.get('skip_condition')
        if not skip_condition:
            return False

        agent_name = agent_config.get('agent_type', 'unknown')

        try:
            from agent_actions.response_processing.where_parser import evaluate_safe_skip_condition

            context = {
                'previous_outputs': previous_outputs or {},
                'agent_config': agent_config
            }

            should_skip = evaluate_safe_skip_condition(skip_condition, context)

            if should_skip:
                self.console.print(f'[yellow]🔍 Agent {agent_name} SKIPPED: skip_condition evaluated to True[/yellow]')
            else:
                self.console.print(f'[green]✓ Agent {agent_name} passed skip_condition check[/green]')

            return should_skip

        except Exception as e:
            logger.warning(
                "Error evaluating skip condition for %s: %s",
                agent_name, e,
                exc_info=True,
                extra={'agent_name': agent_name, 'operation': 'skip_condition_evaluation'}
            )
            return False  # Don't skip on error


class WhereClauseStrategy(SkipStrategy):
    """Strategy for evaluating 'where_clause' with scope='agent'."""

    def get_strategy_name(self) -> str:
        return "where_clause"

    def should_skip(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any]) -> bool:
        """Evaluate agent-level WHERE clause."""
        where_config = agent_config.get('where_clause')

        # Only handle agent-scope where clauses
        if not where_config or where_config.get('scope') != 'agent':
            return False

        agent_name = agent_config.get('agent_type', 'unknown')
        where_clause = where_config['clause']
        passthrough_on_error = where_config.get('passthrough_on_error', True)

        try:
            from agent_actions.response_processing.where_parser import get_global_filter

            filter_service = get_global_filter()

            context_data = {
                'previous_outputs': previous_outputs or {},
                'agent_type': agent_config.get('agent_type'),
                'dependencies': agent_config.get('dependencies', []),
                'agent_config': {
                    k: v for k, v in agent_config.items()
                    if k not in ['where_clause']
                }
            }

            logger.debug(
                "Evaluating agent-level WHERE clause for %s",
                agent_name,
                extra={
                    'agent_name': agent_name,
                    'where_clause': where_clause,
                    'operation': 'where_clause_evaluation'
                }
            )

            filter_result = filter_service.filter_item(
                context_data,
                where_clause,
                timeout=agent_config.get('max_execution_time', 5)
            )

            # Handle filter execution errors
            if not filter_result.success:
                error_msg = filter_result.error or 'Unknown filter error'
                logger.warning(
                    "WHERE clause evaluation failed for %s: %s",
                    agent_name, error_msg,
                    exc_info=True,
                    extra={
                        'agent_name': agent_name,
                        'where_clause': where_clause,
                        'operation': 'where_clause_evaluation'
                    }
                )

                if passthrough_on_error:
                    logger.debug(
                        "Agent %s proceeding despite WHERE clause error (passthrough_on_error=True)",
                        agent_name,
                        extra={'agent_name': agent_name, 'passthrough_on_error': True}
                    )
                    return False
                else:
                    self.console.print(f'[red]→ Agent {agent_name} SKIPPED due to passthrough_on_error=False[/red]')
                    return True

            # Handle filter result
            if not filter_result.matched:
                self.console.print(f'[yellow]🚫 Agent {agent_name} SKIPPED: WHERE clause condition not met[/yellow]')
                logger.debug(
                    "WHERE clause details: %s",
                    where_clause,
                    extra={
                        'agent_name': agent_name,
                        'where_clause': where_clause,
                        'context_data': context_data,
                        'operation': 'where_clause_evaluation'
                    }
                )
                return True
            else:
                self.console.print(f'[green]✓ Agent {agent_name} passed WHERE clause check (execution time: {filter_result.execution_time:.3f}s)[/green]')
                return False

        except Exception as e:
            logger.warning(
                "Error evaluating WHERE clause for %s: %s",
                agent_name, e,
                exc_info=True,
                extra={
                    'agent_name': agent_name,
                    'where_clause': where_clause,
                    'operation': 'where_clause_evaluation'
                }
            )

            if passthrough_on_error:
                logger.debug(
                    "Agent %s proceeding despite error (passthrough_on_error=True)",
                    agent_name,
                    extra={'agent_name': agent_name, 'passthrough_on_error': True}
                )
                return False
            else:
                self.console.print(f'[red]→ Agent {agent_name} SKIPPED due to error and passthrough_on_error=False[/red]')
                return True


class LegacySkipIfStrategy(SkipStrategy):
    """Strategy for evaluating legacy 'skip_if' field."""

    def get_strategy_name(self) -> str:
        return "skip_if (legacy)"

    def should_skip(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any]) -> bool:
        """Evaluate legacy skip_if condition."""
        skip_if = agent_config.get('skip_if')
        if not skip_if:
            return False

        agent_name = agent_config.get('agent_type', 'unknown')

        try:
            from agent_actions.response_processing.where_parser import evaluate_safe_expression

            context = {
                'previous_outputs': previous_outputs or {},
                'agent_config': agent_config
            }

            should_skip = evaluate_safe_expression(skip_if, context)

            if should_skip:
                self.console.print(f'[yellow]🔍 Agent {agent_name} SKIPPED: legacy skip_if condition[/yellow]')
            else:
                self.console.print(f'[green]✓ Agent {agent_name} passed legacy skip_if check[/green]')

            return should_skip

        except Exception as e:
            logger.warning(
                "Error evaluating legacy skip_if condition for %s: %s",
                agent_name, e,
                exc_info=True,
                extra={
                    'agent_name': agent_name,
                    'skip_if': skip_if,
                    'operation': 'legacy_skip_if_evaluation'
                }
            )
            return False  # Don't skip on error


class SkipEvaluator:
    """
    Orchestrates skip condition evaluation using strategy pattern.

    Evaluates skip conditions in order of precedence:
    1. skip_condition
    2. where_clause (scope=agent)
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
            WhereClauseStrategy(self.console),
            LegacySkipIfStrategy(self.console),
        ]

    def should_skip_agent(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any] = None) -> bool:
        """
        Determine if an agent should be skipped based on skip conditions.

        Evaluates all skip strategies in order. Returns True at first skip condition that matches.

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
            except Exception as e:
                agent_name = agent_config.get('agent_type', 'unknown')
                logger.error(
                    "Unexpected error in skip strategy %s for %s: %s",
                    strategy.get_strategy_name(), agent_name, e,
                    exc_info=True,
                    extra={
                        'agent_name': agent_name,
                        'strategy_name': strategy.get_strategy_name(),
                        'operation': 'skip_strategy_evaluation'
                    }
                )
                # Continue to next strategy on error

        return False  # No strategy indicated skip
