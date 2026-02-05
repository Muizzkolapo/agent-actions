"""
Online (synchronous) invocation strategy.

Part of Phase 3 (#891): Extract LLM invocation into strategy pattern.

Extracted from RecordProcessor._execute_llm() for unified invocation handling.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.invocation.strategy import InvocationStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.processing.types import (
    RecoveryMetadata,
    RepromptMetadata,
    RetryMetadata,
)

if TYPE_CHECKING:
    from agent_actions.processing.recovery.reprompt import RepromptService
    from agent_actions.processing.recovery.retry import RetryService
    from agent_actions.processing.types import ProcessingContext

logger = logging.getLogger(__name__)


class OnlineStrategy(InvocationStrategy):
    """
    Synchronous LLM invocation with retry/reprompt support.

    Executes LLM calls immediately and returns response.
    Supports recovery mechanisms:
    - Retry: Re-execute on transient failures
    - Reprompt: Re-execute with feedback on validation failure

    Example:
        strategy = OnlineStrategy(retry_service, reprompt_service)
        result = strategy.invoke(prepared_task, context)

        if result.executed:
            process(result.response)
        elif result.recovery_metadata:
            log_recovery(result.recovery_metadata)
    """

    def __init__(
        self,
        retry_service: Optional["RetryService"] = None,
        reprompt_service: Optional["RepromptService"] = None,
    ):
        """
        Initialize OnlineStrategy.

        Args:
            retry_service: Optional retry service for transient failures
            reprompt_service: Optional reprompt service for validation failures
        """
        self._retry_service = retry_service
        self._reprompt_service = reprompt_service

    def invoke(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
    ) -> InvocationResult:
        """
        Execute LLM synchronously with optional recovery.

        Guard evaluation is already done by TaskPreparer. This method
        passes skip_guard_eval=True to run_dynamic_agent().

        Args:
            task: PreparedTask from TaskPreparer
            context: ProcessingContext with agent config

        Returns:
            InvocationResult with response or recovery metadata
        """
        # Defensive: processor handles guard routing before invoke(), but
        # strategies must also handle it for direct callers bypassing processor.
        if not task.should_execute:
            if task.is_passthrough:
                return InvocationResult.skipped(
                    passthrough_data=task.original_content,
                    passthrough_fields=task.passthrough_fields,
                )
            return InvocationResult.filtered()

        # Execute with appropriate recovery strategy
        recovery_metadata = RecoveryMetadata()

        retry_service = self._retry_service
        reprompt_service = self._reprompt_service

        if reprompt_service and retry_service:
            response, executed, recovery_metadata = self._invoke_with_retry_and_reprompt(
                task, context, recovery_metadata, retry_service, reprompt_service
            )
        elif reprompt_service:
            response, executed, recovery_metadata = self._invoke_with_reprompt(
                task, context, recovery_metadata, reprompt_service
            )
        elif retry_service:
            response, executed, recovery_metadata = self._invoke_with_retry(
                task, context, recovery_metadata, retry_service
            )
        else:
            response, executed = self._invoke_direct(task, context)

        return InvocationResult.immediate(
            response=response,
            executed=executed,
            passthrough_fields=task.passthrough_fields,
            recovery=recovery_metadata if not recovery_metadata.is_empty() else None,
        )

    def supports_recovery(self) -> bool:
        """OnlineStrategy supports retry/reprompt recovery."""
        return True

    def _invoke_direct(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
    ) -> Tuple[Any, bool]:
        """
        Direct LLM call without recovery.

        Args:
            task: PreparedTask
            context: ProcessingContext

        Returns:
            Tuple of (response, executed)
        """
        from agent_actions.processing.helpers import run_dynamic_agent

        tools_path = context.agent_config.get("tools", {}).get("path")

        return run_dynamic_agent(
            context.agent_config,
            context.agent_name,
            task.original_content,
            task.formatted_prompt,
            tools_path=tools_path,
            llm_context=task.llm_context,
            skip_guard_eval=True,
        )

    def _invoke_with_retry(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
        recovery_metadata: RecoveryMetadata,
        retry_service: "RetryService",
    ) -> Tuple[Any, bool, RecoveryMetadata]:
        """
        LLM call with retry protection.

        Args:
            task: PreparedTask
            context: ProcessingContext
            recovery_metadata: Container for recovery tracking
            retry_service: RetryService instance

        Returns:
            Tuple of (response, executed, recovery_metadata)
        """
        from agent_actions.processing.helpers import run_dynamic_agent

        tools_path = context.agent_config.get("tools", {}).get("path")

        def llm_operation():
            return run_dynamic_agent(
                context.agent_config,
                context.agent_name,
                task.original_content,
                task.formatted_prompt,
                tools_path=tools_path,
                llm_context=task.llm_context,
                skip_guard_eval=True,
            )

        retry_result = retry_service.execute(
            llm_operation,
            context=f"action={context.agent_name}",
        )

        # Track retry metadata
        if retry_result.needed_retry:
            succeeded = not retry_result.exhausted
            failures = retry_result.attempts - 1 if succeeded else retry_result.attempts
            recovery_metadata.retry = RetryMetadata(
                attempts=retry_result.attempts,
                failures=failures,
                succeeded=succeeded,
                reason=retry_result.reason or "unknown",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        if retry_result.exhausted:
            logger.warning(
                "Retry exhausted for action %s after %d attempts: %s",
                context.agent_name,
                retry_result.attempts,
                retry_result.last_error,
            )
            return None, False, recovery_metadata

        # Unpack response tuple from run_dynamic_agent
        if retry_result.response:
            response, executed = retry_result.response
        else:
            response, executed = None, False

        return response, executed, recovery_metadata

    def _invoke_with_reprompt(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
        recovery_metadata: RecoveryMetadata,
        reprompt_service: "RepromptService",
    ) -> Tuple[Any, bool, RecoveryMetadata]:
        """
        LLM call with reprompt validation.

        Args:
            task: PreparedTask
            context: ProcessingContext
            recovery_metadata: Container for recovery tracking
            reprompt_service: RepromptService instance

        Returns:
            Tuple of (response, executed, recovery_metadata)
        """
        from agent_actions.processing.helpers import run_dynamic_agent

        tools_path = context.agent_config.get("tools", {}).get("path")

        def llm_direct(prompt: str):
            return run_dynamic_agent(
                context.agent_config,
                context.agent_name,
                task.original_content,
                prompt,
                tools_path=tools_path,
                llm_context=task.llm_context,
                skip_guard_eval=True,
            )

        reprompt_result = reprompt_service.execute(
            llm_operation=llm_direct,
            original_prompt=task.formatted_prompt,
            context=f"action={context.agent_name}",
        )

        # Track reprompt metadata (only if reprompting actually occurred)
        if reprompt_result.attempts > 1:
            recovery_metadata.reprompt = RepromptMetadata(
                attempts=reprompt_result.attempts,
                passed=reprompt_result.passed,
                validation=reprompt_result.validation_name,
            )

        return reprompt_result.response, reprompt_result.executed, recovery_metadata

    def _invoke_with_retry_and_reprompt(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
        recovery_metadata: RecoveryMetadata,
        retry_service: "RetryService",
        reprompt_service: "RepromptService",
    ) -> Tuple[Any, bool, RecoveryMetadata]:
        """
        LLM call with both retry and reprompt (reprompt wraps retry).

        Each reprompt attempt gets independent retry protection.

        Args:
            task: PreparedTask
            context: ProcessingContext
            recovery_metadata: Container for recovery tracking
            retry_service: RetryService instance
            reprompt_service: RepromptService instance

        Returns:
            Tuple of (response, executed, recovery_metadata)
        """
        from agent_actions.processing.helpers import run_dynamic_agent

        tools_path = context.agent_config.get("tools", {}).get("path")

        def llm_with_retry(prompt: str):
            """LLM execution with retry protection, using provided prompt."""

            def llm_call():
                return run_dynamic_agent(
                    context.agent_config,
                    context.agent_name,
                    task.original_content,
                    prompt,
                    tools_path=tools_path,
                    llm_context=task.llm_context,
                    skip_guard_eval=True,
                )

            retry_result = retry_service.execute(
                llm_call,
                context=f"action={context.agent_name}",
            )

            # Track retry metadata
            if retry_result.needed_retry:
                succeeded = not retry_result.exhausted
                failures = retry_result.attempts - 1 if succeeded else retry_result.attempts
                recovery_metadata.retry = RetryMetadata(
                    attempts=retry_result.attempts,
                    failures=failures,
                    succeeded=succeeded,
                    reason=retry_result.reason or "unknown",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            if retry_result.exhausted:
                return None, False

            return retry_result.response

        reprompt_result = reprompt_service.execute(
            llm_operation=llm_with_retry,
            original_prompt=task.formatted_prompt,
            context=f"action={context.agent_name}",
        )

        # Track reprompt metadata (only if reprompting actually occurred)
        if reprompt_result.attempts > 1:
            recovery_metadata.reprompt = RepromptMetadata(
                attempts=reprompt_result.attempts,
                passed=reprompt_result.passed,
                validation=reprompt_result.validation_name,
            )

        if reprompt_result.exhausted:
            logger.warning(
                "Reprompt exhausted for action %s after %d attempts",
                context.agent_name,
                reprompt_result.attempts,
            )

        return reprompt_result.response, reprompt_result.executed, recovery_metadata
