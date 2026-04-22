"""Online (synchronous) invocation strategy with retry/reprompt support."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.invocation.strategy import InvocationStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.processing.recovery.retry import RetryExhaustedException
from agent_actions.processing.types import (
    RecoveryMetadata,
    RepromptMetadata,
    RetryMetadata,
)

if TYPE_CHECKING:
    from agent_actions.processing.recovery.reprompt import RepromptService
    from agent_actions.processing.recovery.retry import RetryResult, RetryService
    from agent_actions.processing.types import ProcessingContext

logger = logging.getLogger(__name__)


class OnlineStrategy(InvocationStrategy):
    """Synchronous LLM invocation with retry/reprompt support."""

    def __init__(
        self,
        retry_service: RetryService | None = None,
        reprompt_service: RepromptService | None = None,
    ):
        self._retry_service = retry_service
        self._reprompt_service = reprompt_service

    def invoke(
        self,
        task: PreparedTask,
        context: ProcessingContext,
    ) -> InvocationResult:
        """Execute LLM synchronously with optional retry/reprompt recovery."""
        if not task.should_execute:
            if task.is_passthrough:
                return InvocationResult.skipped(
                    passthrough_data=task.original_content,
                    passthrough_fields=task.passthrough_fields,
                )
            return InvocationResult.filtered()

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
            response, executed = self._call_llm(task, context, task.formatted_prompt)

        return InvocationResult.immediate(
            response=response,
            executed=executed,
            passthrough_fields=task.passthrough_fields,
            recovery=recovery_metadata if not recovery_metadata.is_empty() else None,
        )

    def supports_recovery(self) -> bool:
        """OnlineStrategy supports retry/reprompt recovery."""
        return True

    def _call_llm(
        self,
        task: PreparedTask,
        context: ProcessingContext,
        prompt: str,
    ) -> tuple[Any, bool]:
        """Execute a single LLM call, returning (response, executed)."""
        from agent_actions.processing.helpers import run_dynamic_agent

        agent_config = cast(dict[str, Any], context.agent_config)
        tools_path = agent_config.get("tools", {}).get("path")
        return run_dynamic_agent(
            agent_config,
            context.agent_name,
            task.original_content,
            prompt,
            tools_path=tools_path,
            llm_context=task.llm_context,
            skip_guard_eval=True,
            skip_schema_validation=self._reprompt_service is not None,
        )

    def _track_retry_metadata(
        self,
        retry_result: RetryResult,
        recovery_metadata: RecoveryMetadata,
    ) -> None:
        """Update recovery_metadata with retry attempt info from retry_result."""
        if retry_result.needed_retry:
            succeeded = not retry_result.exhausted
            failures = retry_result.attempts - 1 if succeeded else retry_result.attempts
            recovery_metadata.retry = RetryMetadata(
                attempts=retry_result.attempts,
                failures=failures,
                succeeded=succeeded,
                reason=retry_result.reason or "unknown",
                timestamp=datetime.now(UTC).isoformat(),
            )

    def _invoke_with_retry(
        self,
        task: PreparedTask,
        context: ProcessingContext,
        recovery_metadata: RecoveryMetadata,
        retry_service: RetryService,
    ) -> tuple[Any, bool, RecoveryMetadata]:
        """LLM call with retry protection."""
        retry_result = retry_service.execute(
            lambda: self._call_llm(task, context, task.formatted_prompt),
            context=f"action={context.agent_name}",
        )

        self._track_retry_metadata(retry_result, recovery_metadata)

        if retry_result.exhausted:
            logger.warning(
                "Retry exhausted for action %s after %d attempts: %s",
                context.agent_name,
                retry_result.attempts,
                retry_result.last_error,
            )
            return None, False, recovery_metadata

        if retry_result.response is not None:
            response, executed = retry_result.response
        else:
            response, executed = None, False

        return response, executed, recovery_metadata

    def _invoke_with_reprompt(
        self,
        task: PreparedTask,
        context: ProcessingContext,
        recovery_metadata: RecoveryMetadata,
        reprompt_service: RepromptService,
    ) -> tuple[Any, bool, RecoveryMetadata]:
        """LLM call with reprompt validation."""
        reprompt_result = reprompt_service.execute(
            llm_operation=lambda prompt: self._call_llm(task, context, prompt),
            original_prompt=task.formatted_prompt,
            context=f"action={context.agent_name}",
        )

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
        context: ProcessingContext,
        recovery_metadata: RecoveryMetadata,
        retry_service: RetryService,
        reprompt_service: RepromptService,
    ) -> tuple[Any, bool, RecoveryMetadata]:
        """LLM call with both retry and reprompt (reprompt wraps retry)."""

        def llm_with_retry(prompt: str):
            retry_result = retry_service.execute(
                lambda: self._call_llm(task, context, prompt),
                context=f"action={context.agent_name}",
            )
            self._track_retry_metadata(retry_result, recovery_metadata)

            if retry_result.exhausted:
                raise RetryExhaustedException(retry_result)
            return retry_result.response

        reprompt_result = reprompt_service.execute(
            llm_operation=llm_with_retry,
            original_prompt=task.formatted_prompt,
            context=f"action={context.agent_name}",
        )

        if reprompt_result.attempts > 1 or reprompt_result.exhausted:
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
