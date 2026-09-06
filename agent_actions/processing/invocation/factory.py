"""Factory for creating invocation strategies."""

from __future__ import annotations

from typing import Any

from agent_actions.config.types import RunMode
from agent_actions.processing.invocation.batch import BatchStrategy
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.invocation.strategy import BatchProvider, InvocationStrategy


class InvocationStrategyFactory:
    """Create invocation strategies based on processing mode."""

    @staticmethod
    def create(
        mode: RunMode,
        agent_config: dict[str, Any],
        provider: BatchProvider | None = None,
    ) -> InvocationStrategy:
        """Create appropriate strategy based on processing mode.

        Raises:
            ValueError: If BATCH mode requested without provider.
        """
        if mode == RunMode.BATCH:
            if provider is None:
                raise ValueError(
                    f"BatchProvider required for BATCH mode (action: '{agent_config.get('agent_type', 'unknown')}')"
                )
            return BatchStrategy(provider)

        return InvocationStrategyFactory._create_online_strategy(agent_config)

    @staticmethod
    def _create_online_strategy(agent_config: dict[str, Any]) -> OnlineStrategy:
        """Create OnlineStrategy with configured recovery services."""
        from agent_actions.expectations.service import (
            create_expectation_service_from_config,
        )
        from agent_actions.processing.helpers import _is_tool_action
        from agent_actions.processing.recovery.retry import (
            create_retry_service_from_config,
        )

        retry_service = create_retry_service_from_config(agent_config.get("retry"))

        expect_config = agent_config.get("expect")
        action_name = agent_config.get("name", "unknown")

        # Reprompt is meaningless for deterministic tools — re-running the same UDF yields the same output.
        if _is_tool_action(agent_config):
            if expect_config is not None and expect_config.get("repair", "auto") != "none":
                from agent_actions.errors import ConfigurationError

                raise ConfigurationError(
                    f"Tool action '{action_name}' cannot repair: re-running a "
                    "deterministic UDF yields the same output. Use repair: none.",
                    context={"action": action_name},
                )
            return OnlineStrategy(
                retry_service=retry_service,
                expectation_service=create_expectation_service_from_config(
                    expect_config, action_name=action_name, agent_config=agent_config
                ),
            )

        return OnlineStrategy(
            retry_service=retry_service,
            expectation_service=create_expectation_service_from_config(
                expect_config, action_name=action_name, agent_config=agent_config
            ),
        )
