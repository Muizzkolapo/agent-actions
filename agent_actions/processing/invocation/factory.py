"""
Factory for creating invocation strategies.

Part of Phase 3 (#891): Extract LLM invocation into strategy pattern.
"""

from typing import Any, Optional

from agent_actions.processing.invocation.batch import BatchStrategy
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.invocation.strategy import BatchProvider, InvocationStrategy
from agent_actions.processing.types import ProcessingMode


class InvocationStrategyFactory:
    """
    Factory for creating appropriate invocation strategy based on mode.

    Example:
        # Online mode with recovery
        strategy = InvocationStrategyFactory.create(
            mode=ProcessingMode.ONLINE,
            agent_config=config,
        )

        # Batch mode
        strategy = InvocationStrategyFactory.create(
            mode=ProcessingMode.BATCH,
            agent_config=config,
            provider=batch_provider,
        )
    """

    @staticmethod
    def create(
        mode: ProcessingMode,
        agent_config: dict[str, Any],
        provider: Optional[BatchProvider] = None,
    ) -> InvocationStrategy:
        """
        Create appropriate strategy based on processing mode.

        Args:
            mode: ProcessingMode (ONLINE or BATCH)
            agent_config: Agent configuration dict
            provider: Batch provider (required for BATCH mode)

        Returns:
            InvocationStrategy instance

        Raises:
            ValueError: If BATCH mode requested without provider
        """
        if mode == ProcessingMode.BATCH:
            if provider is None:
                raise ValueError("BatchProvider required for BATCH mode")
            return BatchStrategy(provider)

        # Online mode - create with optional recovery services
        return InvocationStrategyFactory._create_online_strategy(agent_config)

    @staticmethod
    def _create_online_strategy(agent_config: dict[str, Any]) -> OnlineStrategy:
        """
        Create OnlineStrategy with configured recovery services.

        Args:
            agent_config: Agent configuration dict

        Returns:
            OnlineStrategy with retry/reprompt services if configured
        """
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
    def _build_validator(agent_config: dict[str, Any]) -> Optional["ResponseValidator"]:
        """Compose a ``ResponseValidator`` from agent config.

        Combines UDF validation (``reprompt.validation``) and schema
        validation (``on_schema_mismatch: reprompt``) into a single
        validator.  Returns *None* when neither is configured.
        """
        from agent_actions.processing.helpers import _resolve_schema_mismatch_mode
        from agent_actions.processing.recovery.response_validator import (
            ComposedValidator,
            ResponseValidator,
            SchemaValidator,
            UdfValidator,
        )
        from agent_actions.utils.constants import SCHEMA_KEY, STRICT_SCHEMA_KEY

        validators: list[ResponseValidator] = []

        # UDF validator (from reprompt config)
        reprompt_config = agent_config.get("reprompt")
        if reprompt_config:
            validation_name = reprompt_config.get("validation")
            if validation_name:
                validators.append(UdfValidator(validation_name))

        # Schema validator (when on_schema_mismatch == "reprompt")
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
        """
        Convenience method to create OnlineStrategy directly.

        Args:
            agent_config: Agent configuration dict

        Returns:
            OnlineStrategy instance
        """
        return InvocationStrategyFactory._create_online_strategy(agent_config)

    @staticmethod
    def create_batch(provider: BatchProvider) -> BatchStrategy:
        """
        Convenience method to create BatchStrategy directly.

        Args:
            provider: Batch provider instance

        Returns:
            BatchStrategy instance
        """
        return BatchStrategy(provider)
