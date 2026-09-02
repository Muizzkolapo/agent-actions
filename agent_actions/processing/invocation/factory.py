"""Factory for creating invocation strategies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.processing.recovery.response_validator import ResponseValidator

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
        from agent_actions.processing.recovery.reprompt import (
            create_reprompt_service_from_config,
        )
        from agent_actions.processing.recovery.retry import (
            create_retry_service_from_config,
        )

        retry_config = agent_config.get("retry")
        reprompt_config = agent_config.get("reprompt")

        validator = InvocationStrategyFactory._build_validator(agent_config)

        retry_service = create_retry_service_from_config(retry_config)

        expect_config = agent_config.get("expect")
        action_name = agent_config.get("name", "unknown")

        # Reprompt is meaningless for deterministic tools — re-running the same UDF yields the same output.
        if _is_tool_action(agent_config):
            if expect_config and expect_config.get("repair", "auto") != "none":
                from agent_actions.errors import ConfigurationError

                raise ConfigurationError(
                    f"Tool action '{action_name}' cannot repair: re-running a "
                    "deterministic UDF yields the same output. Use repair: none.",
                    context={"action": action_name},
                )
            return OnlineStrategy(
                retry_service=retry_service,
                reprompt_service=None,
                expectation_service=create_expectation_service_from_config(
                    expect_config,
                    action_name=action_name,
                    schema_name=agent_config.get("schema_name") or None,
                ),
            )

        critique_fn = None
        if reprompt_config and reprompt_config.get("use_llm_critique"):
            from agent_actions.processing.recovery.critique import invoke_critique

            def critique_fn(response: Any, errors: str) -> str:
                return invoke_critique(agent_config, response, errors)

        reprompt_service = create_reprompt_service_from_config(
            reprompt_config, validator=validator, critique_fn=critique_fn
        )

        return OnlineStrategy(
            retry_service=retry_service,
            reprompt_service=reprompt_service,
            expectation_service=create_expectation_service_from_config(
                expect_config,
                action_name=action_name,
                schema_name=agent_config.get("schema_name") or None,
            ),
        )

    @staticmethod
    def _build_validator(agent_config: dict[str, Any]) -> ResponseValidator | None:
        """Compose a ResponseValidator from UDF and schema config, or return None."""
        from agent_actions.processing.helpers import _resolve_schema_mismatch_mode
        from agent_actions.processing.recovery.response_validator import (
            ComposedValidator,
            SchemaValidator,
            UdfValidator,
        )
        from agent_actions.utils.constants import SCHEMA_KEY

        validators: list[ResponseValidator] = []

        reprompt_config = agent_config.get("reprompt")
        if reprompt_config:
            validation_name = reprompt_config.get("validation")
            if validation_name:
                validators.append(UdfValidator(validation_name))

        schema = agent_config.get(SCHEMA_KEY)
        if schema and isinstance(schema, dict):
            mode = _resolve_schema_mismatch_mode(agent_config)
            if mode == "reprompt":
                action_name = agent_config.get("name", "unknown")
                validators.append(SchemaValidator(schema, action_name))

        if not validators:
            return None
        if len(validators) == 1:
            return validators[0]
        return ComposedValidator(validators)
