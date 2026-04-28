"""Record-level processor: thin wrapper around OnlineLLMStrategy.

Delegates per-record logic to OnlineLLMStrategy.process_record() and adds
enrichment + completion events on top.  Other callers (initial_pipeline,
data_generator) still use this class.  Will be removed once all callers
migrate to UnifiedProcessor.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Optional

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError, SchemaValidationError
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.data_pipeline_events import (
    BatchDataProcessingCompleteEvent,
    BatchProcessingProgressEvent,
    BatchProcessingStartedEvent,
    RecordProcessingCompleteEvent,
)
from agent_actions.logging.events.llm_events import TemplateRenderingFailedEvent
from agent_actions.output.response.config_fields import get_default
from agent_actions.utils.constants import HITL_FILE_GRANULARITY_ERROR

from .enrichment import EnrichmentPipeline
from .invocation import BatchProvider, InvocationStrategy, InvocationStrategyFactory
from .strategies.online_llm import OnlineLLMStrategy
from .task_preparer import TaskPreparer
from .types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)

logger = logging.getLogger(__name__)


class RecordProcessor:
    """Thin wrapper: delegates per-record logic to OnlineLLMStrategy, adds enrichment."""

    @classmethod
    def create(
        cls,
        agent_config: dict[str, Any],
        agent_name: str,
    ) -> "RecordProcessor":
        """Create a RecordProcessor with standard online-mode defaults.

        Production code that needs custom strategy/mode/provider should
        use the constructor directly.
        """
        return cls(agent_config=agent_config, agent_name=agent_name)

    def __init__(
        self,
        agent_config: dict[str, Any],
        agent_name: str,
        strategy: InvocationStrategy | None = None,
        mode: RunMode = RunMode.ONLINE,
        provider: Optional["BatchProvider"] = None,
    ):
        self.agent_config = agent_config
        self.agent_name = agent_name

        if strategy is not None and (mode != RunMode.ONLINE or provider is not None):
            logger.warning(
                "Both 'strategy' and 'mode'/'provider' specified for %s; "
                "'strategy' takes precedence",
                agent_name,
            )

        granularity = agent_config.get("granularity", get_default("granularity"))
        action_kind = (agent_config.get("kind") or "").lower()

        # FILE granularity only allowed for tool and HITL actions
        is_file_granularity = isinstance(granularity, str) and granularity.lower() == "file"
        if is_file_granularity:
            if action_kind not in ["tool", "hitl"]:
                raise ConfigurationError(
                    "FILE granularity is only supported for tool and hitl actions. "
                    "LLM actions must use RECORD granularity.",
                    context={
                        "agent_name": agent_name,
                        "granularity": granularity,
                        "kind": action_kind or "(not set)",
                    },
                )

        # HITL actions require FILE granularity — Record mode launches a
        # separate approval UI per record, which is broken UX.
        if action_kind == "hitl" and not is_file_granularity:
            raise ConfigurationError(
                HITL_FILE_GRANULARITY_ERROR,
                context={
                    "agent_name": agent_name,
                    "granularity": granularity,
                    "kind": action_kind,
                },
            )

        self.enrichment_pipeline = EnrichmentPipeline()

        invocation_strategy = strategy or InvocationStrategyFactory.create(
            mode=mode,
            agent_config=agent_config,
            provider=provider,
        )
        self._online_strategy = OnlineLLMStrategy(
            agent_config=agent_config,
            agent_name=agent_name,
            invocation_strategy=invocation_strategy,
        )

    def process(self, item: Any, context: ProcessingContext) -> ProcessingResult:
        """Process a single record through the full pipeline (prepare, invoke, transform, enrich)."""
        result = self._online_strategy.process_record(item, context, skip_guard=False)
        # DEFERRED and FILTERED results skip enrichment (matching old behavior)
        if result.status in (ProcessingStatus.DEFERRED, ProcessingStatus.FILTERED):
            return result
        return self._finalize_result(result, context, result.source_guid)

    def process_batch(self, items: list[Any], context: ProcessingContext) -> list[ProcessingResult]:
        """Process multiple records, capturing per-item failures without aborting the batch."""
        start_time = datetime.now(UTC)

        fire_event(
            BatchProcessingStartedEvent(
                action_name=context.agent_name,
                batch_size=len(items),
            )
        )

        results: list[ProcessingResult] = []
        successes = 0
        failures = 0

        for idx, item in enumerate(items):
            try:
                item_context = self._create_item_context(context, idx, item)
                result = self.process(item, item_context)
                results.append(result)

                if result.status == ProcessingStatus.SUCCESS:
                    successes += 1
                elif result.status == ProcessingStatus.FAILED:
                    failures += 1

                if (idx + 1) % 10 == 0 or (idx + 1) == len(items):
                    fire_event(
                        BatchProcessingProgressEvent(
                            action_name=context.agent_name,
                            processed=idx + 1,
                            total=len(items),
                            successes=successes,
                            failures=failures,
                        )
                    )

            except ConfigurationError:
                raise
            except EmptyOutputError:
                raise
            except TemplateVariableError as e:
                fire_event(
                    TemplateRenderingFailedEvent(
                        action_name=context.agent_name,
                        missing_variables=e.missing_variables,
                        error_message=str(e),
                    )
                )
                raise
            except SchemaValidationError:
                raise
            except Exception as e:
                logger.exception(
                    "[%s] Error processing item %d: %s",
                    context.agent_name,
                    idx,
                    str(e),
                )
                input_record = item if isinstance(item, dict) else None
                source_snapshot = None
                source_guid = None
                if context.is_first_stage:
                    from agent_actions.utils.id_generation import IDGenerator

                    source_guid = IDGenerator.generate_deterministic_source_guid(item)
                    source_snapshot = TaskPreparer._prepare_source_snapshot(item)
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

        elapsed_time = (datetime.now(UTC) - start_time).total_seconds()
        fire_event(
            BatchDataProcessingCompleteEvent(
                action_name=context.agent_name,
                total_records=len(items),
                elapsed_time=elapsed_time,
            )
        )

        return results

    def _finalize_result(
        self,
        result: ProcessingResult,
        context: ProcessingContext,
        source_guid: str | None,
    ) -> ProcessingResult:
        """Enrich a result and fire the completion event."""
        enriched_result = self.enrichment_pipeline.enrich(result, context)
        fire_event(
            RecordProcessingCompleteEvent(
                action_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid or "",
                status=enriched_result.status.value,
            )
        )
        return enriched_result

    @staticmethod
    def _create_item_context(
        base_context: ProcessingContext, index: int, item: Any
    ) -> ProcessingContext:
        """Create per-item context with updated record_index."""
        return replace(
            base_context,
            record_index=index,
            current_item=item if isinstance(item, dict) else None,
        )
