"""Unified record processor replacing StagingProcessor and TargetContentProcessor."""

from typing import Any, Dict, List, Optional, Tuple

from .enrichment import EnrichmentPipeline
from .types import ProcessingContext, ProcessingResult, ProcessingStatus


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
        content, source_guid, source_snapshot = self._normalize_input(item, context)

        # Step 2: Early guard evaluation (FIRST guard check)
        # Evaluates guards on input content to avoid expensive operations
        # if record should be filtered/skipped early
        guard_result = self._evaluate_guard(content, source_guid, context)
        if guard_result is not None:
            return guard_result

        # Step 3: Get source content for prompt
        source_content = self._get_source_content(source_guid, context)

        # Step 4: Prepare prompt
        prep_result = self._prepare_prompt(content, source_content, context)

        # Step 5: Execute LLM
        response, executed, passthrough_fields = self._execute_llm(content, prep_result, context)

        # Step 6: Handle non-execution (SECOND guard check at LLM layer)
        # run_dynamic_agent() returns executed=False if guards skipped execution
        # This happens when guards reference passthrough fields or source content
        # that's only available after prompt preparation (Step 4)
        if not executed:
            if response is None:
                return ProcessingResult.filtered(source_guid=source_guid)
            return ProcessingResult.skipped(
                passthrough_data=response,
                reason="guard_skip",
                source_guid=source_guid,
                passthrough_fields=passthrough_fields,
                source_snapshot=source_snapshot,
            )

        # Step 7: Transform response
        transformed = self._transform_response(
            response, content, source_guid, passthrough_fields, context
        )

        # Step 8: Create success result
        result = ProcessingResult.success(
            data=transformed,
            source_guid=source_guid,
            passthrough_fields=passthrough_fields,
            source_snapshot=source_snapshot,
            raw_response=response,
        )

        # Step 9: Enrich (lineage, metadata, loop IDs, etc.)
        return self.enrichment_pipeline.enrich(result, context)

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
        results = []
        for idx, item in enumerate(items):
            try:
                item_context = self._create_item_context(context, idx, item)
                result = self.process(item, item_context)
                results.append(result)
            except Exception as e:
                # Create failed result instead of propagating exception
                # This allows batch processing to continue
                failed_result = ProcessingResult.failed(
                    error=f"Error processing item {idx}: {str(e)}",
                    source_guid=item.get("source_guid") if isinstance(item, dict) else None,
                )
                results.append(failed_result)
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
            from agent_actions.utilities.id_generation import IDGenerator

            source_guid = IDGenerator.generate_deterministic_source_guid(item)
            # Prepare snapshot with chunk_info filtering
            snapshot = self._prepare_source_snapshot(item)
            return item, source_guid, snapshot
        else:
            # Subsequent-stage expects dict with content/source_guid
            if isinstance(item, dict):
                content = item.get("content", item)
                source_guid = item.get("source_guid")
                return content, source_guid, None
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
        from agent_actions.utilities.processor.processor_helpers import (
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
            return ProcessingResult.filtered(source_guid=source_guid)

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
            return None
        from agent_actions.preprocessing.transformation.data_transformer import (
            DataTransformer,
        )

        return DataTransformer.get_content_by_source_guid(context.source_data, source_guid)

    def _prepare_prompt(self, content: Any, source_content: Any, context: ProcessingContext):
        """
        Prepare prompt using PromptPreparationService.

        Args:
            content: Current content
            source_content: Source content for context
            context: ProcessingContext

        Returns:
            PromptPreparationService result
        """
        from agent_actions.prompt_generation.prompt_preparation_service import (
            PromptPreparationService,
        )

        return PromptPreparationService.prepare_prompt_with_context(
            agent_config=context.agent_config,
            agent_name=context.agent_name,
            contents=content if isinstance(content, dict) else {},
            mode="realtime" if context.mode.value == "online" else "batch",
            source_content=source_content,
            loop_context=context.loop_context,
            workflow_metadata=context.workflow_metadata,
        )

    def _execute_llm(
        self, content: Any, prep_result, context: ProcessingContext
    ) -> Tuple[Any, bool, Dict]:
        """
        Execute LLM invocation (includes SECOND guard check).

        run_dynamic_agent() internally evaluates guards that need prompt-prepared
        context (passthrough fields, {source.*} references). If guard blocks
        execution, returns executed=False.

        Args:
            content: Current content
            prep_result: Prepared prompt result
            context: ProcessingContext

        Returns:
            Tuple of (response, executed, passthrough_fields)
            - response: LLM response or passthrough data if guard skipped
            - executed: False if LLM layer guard blocked execution
            - passthrough_fields: Fields to merge into output
        """
        from agent_actions.utilities.processor.processor_helpers import (
            run_dynamic_agent,
        )

        tools_path = context.agent_config.get("tools", {}).get("path")

        response, executed = run_dynamic_agent(
            context.agent_config,
            context.agent_name,
            content,
            prep_result.formatted_prompt,
            tools_path=tools_path,
        )

        return response, executed, prep_result.passthrough_fields

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
        from agent_actions.utilities.processor.processor_helpers import (
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
        )
