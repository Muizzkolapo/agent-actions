"""Factory for creating invocation strategies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.processing.recovery.response_validator import ResponseValidator

from agent_actions.processing.invocation.batch import BatchStrategy
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.invocation.strategy import BatchProvider, InvocationStrategy
from agent_actions.processing.types import ProcessingMode


class InvocationStrategyFactory:
    """Create invocation strategies based on processing mode."""

    @staticmethod
    def create(
        mode: ProcessingMode,
        agent_config: dict[str, Any],
        provider: BatchProvider | None = None,
    ) -> InvocationStrategy:
        """Create appropriate strategy based on processing mode.

        Raises:
            ValueError: If BATCH mode requested without provider.
        """
        if mode == ProcessingMode.BATCH:
            if provider is None:
                raise ValueError(
                    f"BatchProvider required for BATCH mode (action: '{agent_config.get('agent_type', 'unknown')}')"
                )
            return BatchStrategy(provider)

        return InvocationStrategyFactory._create_online_strategy(agent_config)

    @staticmethod
    def _create_online_strategy(agent_config: dict[str, Any]) -> OnlineStrategy:
        """Create OnlineStrategy with configured recovery services."""
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
        reprompt_service = create_reprompt_service_from_config(reprompt_config, validator=validator)

        return OnlineStrategy(
            retry_service=retry_service,
            reprompt_service=reprompt_service,
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
        from agent_actions.utils.constants import SCHEMA_KEY, STRICT_SCHEMA_KEY

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
                strict = agent_config.get(STRICT_SCHEMA_KEY, False)
                validators.append(SchemaValidator(schema, action_name, strict_mode=strict))

        if not validators:
            return None
        if len(validators) == 1:
            return validators[0]
        return ComposedValidator(validators)

    @staticmethod
    def create_online(
        agent_config: dict[str, Any],
    ) -> OnlineStrategy:
        """Create OnlineStrategy directly."""
        return InvocationStrategyFactory._create_online_strategy(agent_config)

    @staticmethod
    def create_batch(provider: BatchProvider) -> BatchStrategy:
        """Create BatchStrategy directly."""
        return BatchStrategy(provider)
