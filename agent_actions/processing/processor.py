"""Unified record processor replacing StagingProcessor and TargetContentProcessor."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agent_actions.errors import ConfigurationError
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.logging import fire_event
from agent_actions.logging.events.types import (
    TemplateRenderingFailedEvent,
    RecordProcessingStartedEvent,
    RecordFilteredEvent,
    RecordTransformedEvent,
    RecordProcessingCompleteEvent,
    BatchProcessingStartedEvent,
    BatchProcessingProgressEvent,
    BatchProcessingCompleteEvent,
)
from .enrichment import EnrichmentPipeline
from .recovery.retry import RetryService, create_retry_service_from_config
from .types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RepromptMetadata,
    RetryMetadata,
)

logger = logging.getLogger(__name__)


class RecordProcessor:
    """
    Unified processor replacing StagingProcessor + TargetContentProcessor._process_single_item().

    Handles both first-stage (raw input) and subsequent-stage (structured input) processing.

    Guard Evaluation Strategy (Two-Phase):
    ---------------------------------------
    Guards are evaluated in TWO places for optimization and flexibility:

    1. **Early Guard Evaluation (Step 2)**: _evaluate_guard()
       - Evaluates guards based on input content BEFORE expensive operations
       - Avoids unnecessary prompt preparation and LLM calls
       - Guards evaluated: guard.clause, conditional_clause
       - Context: Input content only (no passthrough fields yet)
       - Use case: Filter/skip records based on input fields

    2. **LLM Layer Guard (Step 6)**: Handled by run_dynamic_agent()
       - Evaluates guards AFTER prompt preparation, WITH passthrough fields
       - Guards can reference {source.*} and passthrough fields
       - Returns (response, executed) where executed=False means guard skipped
       - Use case: Guards that need enriched context or source data lookups

    Why Two Phases?
    ---------------
    - Performance: Early evaluation avoids expensive LLM calls (~100ms+ saved)
    - Flexibility: LLM layer can access prompt-prepared passthrough fields
    - Backwards compatibility: Matches old StagingProcessor/TargetContentProcessor behavior

    Example:
    --------
    # Early guard (evaluated on raw input):
    guard:
      clause: "status == 'active'"
      behavior: "skip"
    # → Skipped at Step 2, no LLM call made

    # LLM layer guard (needs passthrough fields):
    guard:
      clause: "{source.priority} == 'high' and length > 100"
      behavior: "skip"
    # → Skipped at Step 6, after prompt preparation adds passthrough fields
    """

    def __init__(self, agent_config: Dict, agent_name: str):
        """
        Initialize RecordProcessor.

        Args:
            agent_config: Agent configuration dict
            agent_name: Agent name for metadata
        """
        self.agent_config = agent_config
        self.agent_name = agent_name

        # Validate granularity setting
        # kind: "tool" = tool action, "llm" = LLM action (default)
        granularity = agent_config.get("granularity", "record")
        action_kind = (agent_config.get("kind") or "").lower()

        # FILE granularity only allowed for tool actions
        is_file_granularity = isinstance(granularity, str) and granularity.lower() == "file"
        if is_file_granularity:
            if action_kind != "tool":
                raise ConfigurationError(
                    "FILE granularity is only supported for tool actions (kind: tool). "
                    "LLM actions must use RECORD granularity.",
                    context={
                        "agent_name": agent_name,
                        "granularity": granularity,
                        "kind": action_kind or "(not set)",
                    },
                )

            # Guards not supported in FILE mode (tool processes entire array at once)
            guard_config = agent_config.get("guard")
            if guard_config:
                raise ConfigurationError(
                    "Guards are not supported with FILE granularity. "
                    "FILE mode processes the entire array at once, so per-record guards cannot be applied. "
                    "Remove the guard or use RECORD granularity.",
                    context={
                        "agent_name": agent_name,
                        "granularity": granularity,
                        "kind": action_kind,
                        "guard": guard_config,
                    },
                )

        self.enrichment_pipeline = EnrichmentPipeline()

    def process(self, item: Any, context: ProcessingContext) -> ProcessingResult:
        """
        Process single record (first-stage or subsequent-stage).

        Processing Pipeline (9 steps):
        1. Normalize input format
        2. Early guard evaluation (on input content)
        3. Get source content for prompt
        4. Prepare prompt (adds passthrough fields)
        5. Execute LLM
        6. Handle non-execution (LLM layer guard check)
        7. Transform response
        8. Create success result
        9. Enrich (lineage, metadata, loop IDs, etc.)

        Note: Guards evaluated TWICE - see class docstring for details on two-phase
        guard evaluation strategy.

        Args:
            item: Input item
                - First-stage: any type (str, list, dict, etc.)
                - Subsequent-stage: dict with {content, source_guid} (recommended)
            context: ProcessingContext with config and state

        Returns:
            ProcessingResult with enriched data
        """
        # Step 1: Normalize input format
        input_record = item if isinstance(item, dict) else None
        content, source_guid, source_snapshot = self._normalize_input(item, context)

        # Fire RP001: Record processing started
        fire_event(
            RecordProcessingStartedEvent(
                agent_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid,
            )
        )

        # Step 2: Early guard evaluation (FIRST guard check)
        # Evaluates guards on input content to avoid expensive operations
        # if record should be filtered/skipped early
        guard_result = self._evaluate_guard(content, source_guid, context)
        if guard_result is not None:
            return guard_result

        # Step 3: Get source content for prompt
        # For first-stage: input content IS the source content (template {{ source.* }})
        # For subsequent-stage: lookup source from source_data by source_guid
        if context.is_first_stage:
            source_content = content
        else:
            source_content = self._get_source_content(source_guid, context)

        # Step 4: Prepare prompt
        # For subsequent-stage, pass the full item as current_item for historical data loading
        current_item = item if isinstance(item, dict) else None
        prep_result = self._prepare_prompt(content, source_content, context, current_item)

        # Step 5: Execute LLM (with optional retry)
        response, executed, passthrough_fields, recovery_metadata = self._execute_llm(
            content, prep_result, context
        )

        # Step 6: Handle non-execution (SECOND guard check at LLM layer or retry exhausted)
        # run_dynamic_agent() returns executed=False if guards skipped execution
        # This happens when guards reference passthrough fields or source content
        # that's only available after prompt preparation (Step 4)
        if not executed:
            if response is None:
                # Check if this is a retry exhaustion vs guard filter
                if recovery_metadata and recovery_metadata.retry:
                    return ProcessingResult.exhausted(
                        error=f"Retry exhausted after {recovery_metadata.retry.attempts} attempts",
                        source_guid=source_guid,
                        recovery_metadata=recovery_metadata,
                        source_snapshot=source_snapshot,  # Preserve for source saving
                        input_record=input_record,
                    )
                # Fire RP002: Record filtered (LLM layer guard filter)
                fire_event(
                    RecordFilteredEvent(
                        agent_name=context.agent_name,
                        record_index=context.record_index,
                        source_guid=source_guid,
                        filter_reason="llm_layer_guard_filter",
                    )
                )
                return ProcessingResult.filtered(
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,  # Preserve for source saving
                    input_record=input_record,
                )
            else:
                # response is not None - guard caused skip rather than filter
                # Fire RP002: Record filtered (LLM layer guard skip)
                fire_event(
                    RecordFilteredEvent(
                        agent_name=context.agent_name,
                        record_index=context.record_index,
                        source_guid=source_guid,
                        filter_reason="llm_layer_guard_skip",
                    )
                )
                return ProcessingResult.skipped(
                    passthrough_data=response,
                    reason="guard_skip",
                    source_guid=source_guid,
                    passthrough_fields=passthrough_fields,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )

        # Step 7: Transform response
        transformed = self._transform_response(
            response, content, source_guid, passthrough_fields, context
        )

        # Fire RP003: Record transformed
        input_size = 1 if not isinstance(response, list) else len(response)
        output_size = len(transformed) if isinstance(transformed, list) else 1
        fire_event(
            RecordTransformedEvent(
                agent_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid,
                input_size=input_size,
                output_size=output_size,
            )
        )

        # Step 8: Create success result (with recovery metadata if retry occurred)
        result = ProcessingResult.success(
            data=transformed,
            source_guid=source_guid,
            passthrough_fields=passthrough_fields,
            source_snapshot=source_snapshot,
            raw_response=response,
            recovery_metadata=recovery_metadata,
            input_record=input_record,
        )

        # Step 9: Enrich (lineage, metadata, loop IDs, etc.)
        enriched_result = self.enrichment_pipeline.enrich(result, context)

        # Fire RP004: Record processing complete
        fire_event(
            RecordProcessingCompleteEvent(
                agent_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid,
                status=enriched_result.status.value,
            )
        )

        return enriched_result

    def process_batch(self, items: List[Any], context: ProcessingContext) -> List[ProcessingResult]:
        """
        Process multiple records.

        Handles exceptions gracefully - if one item fails, it creates a
        ProcessingResult.failed() for that item and continues processing
        remaining items.

        Args:
            items: List of input items
            context: Base ProcessingContext

        Returns:
            List of ProcessingResults (includes both successes and failures)
        """
        # CRITICAL: Capture start_time BEFORE firing start event (learned from TICKET-019 P0)
        from datetime import datetime, timezone

        start_time = datetime.now(timezone.utc)

        # Fire BP001: Batch processing started
        fire_event(
            BatchProcessingStartedEvent(
                agent_name=context.agent_name,
                batch_size=len(items),
            )
        )

        results = []
        successes = 0
        failures = 0

        for idx, item in enumerate(items):
            try:
                item_context = self._create_item_context(context, idx, item)
                result = self.process(item, item_context)
                results.append(result)

                # Track success/failure
                if result.status == ProcessingStatus.SUCCESS:
                    successes += 1
                elif result.status == ProcessingStatus.FAILED:
                    failures += 1

                # Fire BP002: Batch processing progress (every 10 records or at end)
                if (idx + 1) % 10 == 0 or (idx + 1) == len(items):
                    fire_event(
                        BatchProcessingProgressEvent(
                            agent_name=context.agent_name,
                            processed=idx + 1,
                            total=len(items),
                            successes=successes,
                            failures=failures,
                        )
                    )

            except ConfigurationError:
                # ConfigurationError indicates a fundamental workflow misconfiguration
                # Re-raise immediately to fail the workflow - these cannot be recovered
                raise
            except TemplateVariableError as e:
                # TemplateVariableError indicates a code bug (undefined template variables)
                # Re-raise immediately to fail the workflow - these are not data errors
                fire_event(
                    TemplateRenderingFailedEvent(
                        agent_name=context.agent_name,
                        missing_variables=e.missing_variables,
                        error_message=str(e),
                    )
                )
                raise
            except Exception as e:
                # Create failed result instead of propagating exception
                # This allows batch processing to continue for transient/data errors
                # Log the error for debugging
                import logging

                logging.getLogger(__name__).error(
                    f"[{context.agent_name}] Error processing item {idx}: {str(e)}"
                )
                # Preserve source_snapshot and source_guid for first-stage source saving
                input_record = item if isinstance(item, dict) else None
                source_snapshot = None
                source_guid = None
                if context.is_first_stage:
                    from agent_actions.utils.id_generation import IDGenerator

                    source_guid = IDGenerator.generate_deterministic_source_guid(item)
                    source_snapshot = self._prepare_source_snapshot(item)
                else:
                    source_guid = item.get("source_guid") if isinstance(item, dict) else None
                failed_result = ProcessingResult.failed(
                    error=f"Error processing item {idx}: {str(e)}",
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )
                results.append(failed_result)
                failures += 1

        # Fire BP003: Batch processing complete
        elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        fire_event(
            BatchProcessingCompleteEvent(
                agent_name=context.agent_name,
                total_records=len(items),
                elapsed_time=elapsed_time,
            )
        )

        return results

    # Private helper methods

    def _normalize_input(
        self, item: Any, context: ProcessingContext
    ) -> Tuple[Any, str, Optional[Any]]:
        """
        Normalize input format.

        First-stage: raw input → generate source_guid, preserve snapshot
          - Accepts any type: str, list, dict, etc.
        Subsequent-stage: structured {content, source_guid} → extract fields
          - Expects dict with 'content' and 'source_guid' keys

        Args:
            item: Input item (any type for first-stage, dict for subsequent-stage)
            context: ProcessingContext

        Returns:
            Tuple of (content, source_guid, source_snapshot)
        """
        if context.is_first_stage:
            from agent_actions.utils.id_generation import IDGenerator

            source_guid = IDGenerator.generate_deterministic_source_guid(item)
            # Prepare snapshot with chunk_info filtering
            snapshot = self._prepare_source_snapshot(item)
            return item, source_guid, snapshot
        else:
            # Subsequent-stage expects dict with content/source_guid
            if isinstance(item, dict):
                content = item.get("content", item)
                source_guid = item.get("source_guid")
                return content, source_guid, item
            else:
                # Non-dict input in subsequent-stage: treat as raw content
                return item, None, None

    def _prepare_source_snapshot(self, item: Any) -> Any:
        """
        Prepare source snapshot for first-stage processing.

        Preserves StagingProcessor._prepare_source_text() logic:
        - Filters out chunk_info metadata keys for dicts
        - Returns item as-is for non-dict types (str, list, etc.)

        Args:
            item: Input item (any type)

        Returns:
            Filtered snapshot (dict) or original item (for non-dict types)
        """
        if isinstance(item, dict) and "chunk_info" in item:
            excluded_keys = ["target_id", "record_index", "chunk_index"]
            snapshot = {k: v for k, v in item.items() if k not in excluded_keys}
        else:
            snapshot = item.copy() if isinstance(item, dict) else item
        return snapshot

    def _evaluate_guard(
        self, content: Any, source_guid: str, context: ProcessingContext
    ) -> Optional[ProcessingResult]:
        """
        Evaluate guard conditions early (FIRST guard check).

        This is the performance optimization layer - evaluates guards based on
        input content BEFORE expensive prompt preparation and LLM calls.

        Limitations:
        - Cannot access passthrough fields (added in Step 4)
        - Cannot access {source.*} references (requires prompt preparation)
        - Guards referencing these will be evaluated at LLM layer (Step 6)

        Args:
            content: Content to evaluate
            source_guid: Source GUID
            context: ProcessingContext

        Returns:
            ProcessingResult if guard blocks execution, None otherwise
            None means "proceed to prompt preparation and LLM execution"
        """
        from agent_actions.processing.helpers import (
            evaluate_guard_condition,
        )

        guard_config = context.agent_config.get("guard")
        conditional = context.agent_config.get("conditional_clause")

        if not guard_config and not conditional:
            return None

        eval_context = content if isinstance(content, dict) else {"_raw": content}
        should_execute, behavior = evaluate_guard_condition(context.agent_config, eval_context)

        if should_execute:
            return None

        if behavior == "filter":
            # Fire RP002: Record filtered
            fire_event(
                RecordFilteredEvent(
                    agent_name=context.agent_name,
                    record_index=context.record_index if hasattr(context, "record_index") else 0,
                    source_guid=source_guid,
                    filter_reason="guard_filter",
                )
            )
            return ProcessingResult.filtered(source_guid=source_guid)

        # Fire RP002: Record filtered (skip)
        fire_event(
            RecordFilteredEvent(
                agent_name=context.agent_name,
                record_index=context.record_index if hasattr(context, "record_index") else 0,
                source_guid=source_guid,
                filter_reason=f"guard_{behavior}",
            )
        )
        return ProcessingResult.skipped(
            passthrough_data=content,
            reason=f"guard_{behavior}",
            source_guid=source_guid,
        )

    def _get_source_content(self, source_guid: str, context: ProcessingContext) -> Optional[Any]:
        """
        Get source content for prompt preparation.

        Args:
            source_guid: Source GUID to lookup
            context: ProcessingContext

        Returns:
            Source content if found, None otherwise
        """
        if not context.source_data:
            logger.debug(
                "Source data not available for %s; cannot look up source_guid=%s",
                context.agent_name,
                source_guid,
            )
            return None
        from agent_actions.input.preprocessing.transformation.transformer import (
            DataTransformer,
        )

        source_content = DataTransformer.get_content_by_source_guid(
            context.source_data, source_guid
        )
        if source_content is None:
            logger.debug(
                "Could not resolve source content for %s (%s source_data items)",
                context.agent_name,
                len(context.source_data),
            )
        return source_content

    def _prepare_prompt(
        self,
        content: Any,
        source_content: Any,
        context: ProcessingContext,
        current_item: Optional[Dict] = None,
    ):
        """
        Prepare prompt using PromptPreparationService.

        Args:
            content: Current content
            source_content: Source content for context
            context: ProcessingContext
            current_item: Optional full item dict with lineage, source_guid for historical data loading

        Returns:
            PromptPreparationService result
        """
        from agent_actions.prompt.service import (
            PromptPreparationService,
        )
        from agent_actions.utils.tools_resolver import resolve_tools_path

        # Resolve tools_path for function injection (parity with batch mode)
        tools_path = resolve_tools_path(context.agent_config)

        return PromptPreparationService.prepare_prompt_with_context(
            agent_config=context.agent_config,
            agent_name=context.agent_name,
            contents=content if isinstance(content, dict) else {},
            mode="realtime" if context.mode.value == "online" else "batch",
            agent_indices=context.agent_indices,
            dependency_configs=context.dependency_configs,
            source_content=source_content,
            loop_context=context.loop_context,
            workflow_metadata=context.workflow_metadata,
            current_item=current_item,
            file_path=context.file_path,
            tools_path=tools_path,
        )

    def _execute_llm(
        self, content: Any, prep_result, context: ProcessingContext
    ) -> Tuple[Any, bool, Dict, Optional[RecoveryMetadata]]:
        """
        Execute LLM invocation with optional reprompt and retry (includes SECOND guard check).

        run_dynamic_agent() internally evaluates guards that need prompt-prepared
        context (passthrough fields, {source.*} references). If guard blocks
        execution, returns executed=False.

        Recovery Behavior:
        - Reprompt wraps retry (each reprompt attempt gets independent retry protection)
        - If reprompt is enabled, validates LLM response with UDF and re-executes with feedback
        - If retry is enabled, wraps each LLM call with RetryService for transient failures
        - Returns recovery_metadata tracking both reprompt and retry attempts

        Args:
            content: Current content
            prep_result: Prepared prompt result
            context: ProcessingContext

        Returns:
            Tuple of (response, executed, passthrough_fields, recovery_metadata)
            - response: LLM response or passthrough data if guard skipped
            - executed: False if LLM layer guard blocked execution
            - passthrough_fields: Fields to merge into output
            - recovery_metadata: Recovery tracking info (None if no recovery occurred)
        """
        from agent_actions.processing.helpers import (
            run_dynamic_agent,
        )
        from agent_actions.processing.recovery.reprompt import create_reprompt_service_from_config

        tools_path = context.agent_config.get("tools", {}).get("path")

        # Check for retry configuration
        retry_config = context.agent_config.get("retry")
        retry_service = create_retry_service_from_config(retry_config)

        # Check for reprompt configuration
        reprompt_config = context.agent_config.get("reprompt")
        reprompt_service = create_reprompt_service_from_config(reprompt_config)

        # Initialize recovery metadata container
        recovery_metadata = RecoveryMetadata()

        # Branch 1: Both reprompt and retry enabled (reprompt wraps retry)
        if reprompt_service and retry_service:

            def llm_with_retry(prompt: str):
                """LLM execution with retry protection, using provided prompt."""

                def llm_call():
                    return run_dynamic_agent(
                        context.agent_config,
                        context.agent_name,
                        content,
                        prompt,  # Use prompt parameter (includes feedback on reprompt)
                        tools_path=tools_path,
                        llm_context=prep_result.llm_context,
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

            # Execute with reprompt (wraps retry)
            reprompt_result = reprompt_service.execute(
                llm_operation=llm_with_retry,
                original_prompt=prep_result.formatted_prompt,
                context=f"action={context.agent_name}",
            )

            # Track reprompt metadata (only if reprompting actually occurred)
            # attempts=1 means it passed on first try (no reprompt needed)
            # attempts>1 means validation failed at least once and reprompting happened
            if reprompt_result.attempts > 1:
                recovery_metadata.reprompt = RepromptMetadata(
                    attempts=reprompt_result.attempts,
                    passed=reprompt_result.passed,
                    validation=reprompt_result.validation_name,
                )

            # Handle exhausted reprompt
            if reprompt_result.exhausted:
                logger.warning(
                    "Reprompt exhausted for action %s after %d attempts",
                    context.agent_name,
                    reprompt_result.attempts,
                )

            return (
                reprompt_result.response,
                reprompt_result.executed,
                prep_result.passthrough_fields,
                recovery_metadata if not recovery_metadata.is_empty() else None,
            )

        # Branch 2: Only reprompt enabled (no retry)
        elif reprompt_service:

            def llm_direct(prompt: str):
                """Direct LLM execution without retry, using provided prompt."""
                return run_dynamic_agent(
                    context.agent_config,
                    context.agent_name,
                    content,
                    prompt,  # Use prompt parameter (includes feedback on reprompt)
                    tools_path=tools_path,
                    llm_context=prep_result.llm_context,
                )

            reprompt_result = reprompt_service.execute(
                llm_operation=llm_direct,
                original_prompt=prep_result.formatted_prompt,
                context=f"action={context.agent_name}",
            )

            # Track reprompt metadata (only if reprompting actually occurred)
            # attempts=1 means it passed on first try (no reprompt needed)
            # attempts>1 means validation failed at least once and reprompting happened
            if reprompt_result.attempts > 1:
                recovery_metadata.reprompt = RepromptMetadata(
                    attempts=reprompt_result.attempts,
                    passed=reprompt_result.passed,
                    validation=reprompt_result.validation_name,
                )

            return (
                reprompt_result.response,
                reprompt_result.executed,
                prep_result.passthrough_fields,
                recovery_metadata if not recovery_metadata.is_empty() else None,
            )

        # Branch 3: Only retry enabled (no reprompt) - existing logic
        elif retry_service:

            def llm_operation():
                return run_dynamic_agent(
                    context.agent_config,
                    context.agent_name,
                    content,
                    prep_result.formatted_prompt,
                    tools_path=tools_path,
                    llm_context=prep_result.llm_context,
                )

            retry_result = retry_service.execute(
                llm_operation,
                context=f"action={context.agent_name}",
            )

            # Build recovery metadata if retry was triggered
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

            # Handle exhausted case
            if retry_result.exhausted:
                logger.warning(
                    "Retry exhausted for action %s after %d attempts: %s",
                    context.agent_name,
                    retry_result.attempts,
                    retry_result.last_error,
                )
                return (
                    None,
                    False,
                    prep_result.passthrough_fields,
                    recovery_metadata if not recovery_metadata.is_empty() else None,
                )

            # Unpack the response tuple from run_dynamic_agent
            if retry_result.response:
                response, executed = retry_result.response
            else:
                response, executed = None, False

            return (
                response,
                executed,
                prep_result.passthrough_fields,
                recovery_metadata if not recovery_metadata.is_empty() else None,
            )

        # Branch 4: No recovery enabled - direct execution
        else:
            response, executed = run_dynamic_agent(
                context.agent_config,
                context.agent_name,
                content,
                prep_result.formatted_prompt,
                tools_path=tools_path,
                llm_context=prep_result.llm_context,
            )

            return response, executed, prep_result.passthrough_fields, None

    def _transform_response(
        self,
        response: Any,
        content: Any,
        source_guid: str,
        passthrough_fields: Dict,
        context: ProcessingContext,
    ) -> List[Dict]:
        """
        Transform LLM response to output format.

        Args:
            response: LLM response
            content: Original content
            source_guid: Source GUID
            passthrough_fields: Fields to pass through
            context: ProcessingContext

        Returns:
            List of transformed items
        """
        from agent_actions.processing.helpers import (
            transform_with_passthrough,
        )

        return transform_with_passthrough(response, content, source_guid, context.agent_config)

    def _create_item_context(
        self, base_context: ProcessingContext, index: int, item: Any
    ) -> ProcessingContext:
        """
        Create per-item context with updated record_index.

        Args:
            base_context: Base ProcessingContext
            index: Item index
            item: Current item

        Returns:
            New ProcessingContext for this item
        """
        return ProcessingContext(
            agent_config=base_context.agent_config,
            agent_name=base_context.agent_name,
            mode=base_context.mode,
            is_first_stage=base_context.is_first_stage,
            source_data=base_context.source_data,
            file_path=base_context.file_path,
            output_directory=base_context.output_directory,
            loop_context=base_context.loop_context,
            workflow_metadata=base_context.workflow_metadata,
            record_index=index,
            agent_indices=base_context.agent_indices,
            dependency_configs=base_context.dependency_configs,
            current_item=item if isinstance(item, dict) else None,
        )
