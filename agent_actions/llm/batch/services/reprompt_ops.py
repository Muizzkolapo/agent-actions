"""Reprompt and validation operations for batch result quality assurance."""

import logging
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services.retry_polling import (
    import_validation_module,
    wait_for_batch_completion,
)
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.validation_events import (
    RepromptRecoveredEvent,
    RepromptRetryEvent,
)
from agent_actions.output.response.config_fields import get_default
from agent_actions.processing.evaluation.loop import accumulate_failure_types
from agent_actions.processing.recovery.retry import is_retriable_error
from agent_actions.processing.types import RecoveryMetadata

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def _stamp_reprompt_failed(
    records: list["BatchResult"],
    reprompted_ids: dict[str, int],
    validation_name: str,
) -> None:
    """Mark records with ``passed=False`` reprompt metadata.

    Used when records cannot continue the reprompt loop — batch did not
    complete, provider dropped them, or a transient submission error
    interrupted the cycle.  Mutates records in-place.
    """
    from agent_actions.processing.types import RepromptMetadata

    for r in records:
        if not r.recovery_metadata:
            r.recovery_metadata = RecoveryMetadata()
        r.recovery_metadata.reprompt = RepromptMetadata(
            attempts=reprompted_ids.get(r.custom_id, 1),
            passed=False,
            validation=validation_name,
        )


def _load_source_data_for_reprompt(
    storage_backend: "StorageBackend | None",
) -> list[Any] | None:
    """Load source data from the storage backend for reprompt batch preparation.

    During initial batch preparation the runner passes ``source_data`` so the
    ``source.*`` observe namespace can be resolved.  During reprompt the same
    data is needed but is not threaded through the call chain.  This helper
    reads it back from the storage backend (where it was persisted at ingest
    time) so the reprompt preparator can resolve ``source.*`` fields
    identically to the initial batch.

    Returns ``None`` when no backend is configured or no source files exist,
    which preserves the existing fallback behaviour (``source_content = content``).
    """
    if storage_backend is None:
        return None

    try:
        source_files = storage_backend.list_source_files()
        if not source_files:
            return None

        all_source_data: list[Any] = []
        for path in source_files:
            try:
                records = storage_backend.read_source(path)
                all_source_data.extend(records)
            except FileNotFoundError:
                logger.warning("Source file not found during reprompt data load: %s", path)
                continue

        return all_source_data if all_source_data else None
    except Exception:
        logger.warning("Could not load source data for reprompt", exc_info=True)
        return None


def _load_validation_udf(
    agent_config: dict[str, Any] | None,
    reprompt_config: dict[str, Any],
) -> None:
    """Resolve and import the validation module so the UDF is registered."""
    from agent_actions.utils.tools_resolver import resolve_tools_path

    validation_path = reprompt_config.get("validation_path")
    if not validation_path:
        validation_path = resolve_tools_path(agent_config or {})

    validation_module = reprompt_config.get("validation_module", "reprompt_validations")

    if validation_path:
        import_validation_module(validation_module, validation_path)
    else:
        logger.debug(
            "No validation_path configured, attempting direct import of '%s'",
            validation_module,
        )
        import_validation_module(validation_module, None)


def build_evaluation_loop(
    agent_config: dict[str, Any] | None,
    *,
    max_attempts: int | None = None,
    on_exhausted: str | None = None,
) -> tuple | None:
    """Build an EvaluationLoop + ValidationStrategy from agent_config.

    Consolidates the repeated config-parse → UDF-load → strategy-construct
    sequence used by validate_and_reprompt, handle_reprompt_recovery, and
    check_and_submit_reprompt.

    Returns ``(loop, strategy)`` or ``None`` if reprompt is not configured
    or the validation function cannot be resolved.  The validation name
    is available via ``strategy.name``.
    """
    from agent_actions.processing.evaluation import EvaluationLoop
    from agent_actions.processing.evaluation.strategies import ValidationStrategy
    from agent_actions.processing.recovery.reprompt import parse_reprompt_config
    from agent_actions.processing.recovery.response_validator import (
        resolve_feedback_strategies,
    )
    from agent_actions.processing.recovery.validation import get_validation_function

    raw_reprompt_config = (agent_config or {}).get("reprompt")
    parsed = parse_reprompt_config(raw_reprompt_config)
    if parsed is None:
        return None

    _load_validation_udf(agent_config, raw_reprompt_config or {})

    try:
        validation_func, feedback_message = get_validation_function(parsed.validation_name)
    except ValueError as e:
        logger.error("Failed to get validation function: %s", e)
        return None

    strategies = resolve_feedback_strategies(raw_reprompt_config)

    json_mode = (agent_config or {}).get("json_mode", get_default("json_mode"))

    strategy = ValidationStrategy(
        validation_func=validation_func,
        feedback_message=feedback_message,
        strategies=strategies,
        max_attempts=max_attempts if max_attempts is not None else parsed.max_attempts,
        on_exhausted=on_exhausted if on_exhausted is not None else parsed.on_exhausted,
        json_mode=bool(json_mode),
        validation_name=parsed.validation_name,
    )
    return EvaluationLoop(strategy), strategy


def validate_and_reprompt(
    action_indices: dict[str, int],
    dependency_configs: dict[str, dict],
    storage_backend: "StorageBackend | None",
    results: list[BatchResult],
    provider: BaseBatchClient,
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str,
    agent_config: dict[str, Any] | None,
) -> list[BatchResult]:
    """Validate results and reprompt failures using graduated pool pattern.

    Records that pass validation are graduated and never re-validated.
    Only failing records are resubmitted for reprompt.
    Each cycle, the failure set can only shrink — never grow.
    """
    from agent_actions.processing.recovery.response_validator import (
        build_validation_feedback,
    )
    from agent_actions.processing.types import RepromptMetadata

    logger.debug(
        "Batch reprompt check: agent_config has %d keys",
        len(agent_config or {}),
    )
    setup = build_evaluation_loop(agent_config)
    if setup is None:
        logger.debug("Reprompt not configured, skipping validation")
        return results

    loop, strategy = setup
    validation_name = strategy.name
    max_attempts = strategy.max_attempts
    on_exhausted = strategy.on_exhausted
    feedback_message = strategy._feedback_message
    strategies = strategy._strategies
    raw_reprompt_config = (agent_config or {}).get("reprompt") or {}

    source_data = _load_source_data_for_reprompt(storage_backend)
    all_graduated: list[BatchResult] = []
    active_results = results
    reprompted_ids: dict[str, int] = {}
    failure_type_counts: dict[str, dict[str, int]] = {}

    for attempt in range(max_attempts):
        graduated, still_failing, round_failure_types = loop.split(active_results)
        all_graduated.extend(graduated)

        accumulate_failure_types(failure_type_counts, round_failure_types)

        if not still_failing:
            logger.info("All records passed validation after %d attempts", attempt + 1)
            break

        logger.info(
            "Reprompt attempt %d/%d: %d records failed validation",
            attempt + 1,
            max_attempts,
            len(still_failing),
        )

        for r in still_failing:
            reprompted_ids[r.custom_id] = reprompted_ids.get(r.custom_id, 0) + 1

        if attempt == max_attempts - 1:
            from agent_actions.processing.evaluation.exhaustion import (
                apply_exhausted_reprompt,
            )

            failed_ids = {r.custom_id for r in still_failing}
            apply_exhausted_reprompt(
                results=still_failing,
                failed_ids=failed_ids,
                validation_name=validation_name,
                attempt=attempt + 1,
                on_exhausted=on_exhausted,
                per_record_attempts=reprompted_ids,
                failure_type_counts=failure_type_counts or None,
            )
            all_graduated.extend(still_failing)
            break

        fire_event(
            RepromptRetryEvent(
                action_name=file_name,
                attempt=attempt + 2,
                max_attempts=max_attempts,
                error=f"{len(still_failing)} records failed validation",
                failed_count=len(still_failing),
            )
        )

        use_critique = (raw_reprompt_config or {}).get("use_llm_critique", False)
        critique_after = (raw_reprompt_config or {}).get("critique_after_attempt", 2)
        apply_critique = use_critique and attempt + 1 >= critique_after

        if apply_critique:
            from agent_actions.processing.recovery.critique import (
                format_critique_feedback,
                invoke_critique,
            )

            if len(still_failing) > 10:
                logger.info(
                    "Critique enabled for %d failed records — each requires a "
                    "synchronous LLM call, expect increased latency",
                    len(still_failing),
                )

        reprompt_records = []
        for failed_result in still_failing:
            custom_id = failed_result.custom_id

            if custom_id not in context_map:
                logger.warning(
                    "Cannot reprompt %s: not found in context_map",
                    custom_id,
                )
                continue

            original_record = context_map[custom_id].copy()

            feedback = build_validation_feedback(
                failed_response=failed_result.content,
                feedback_message=feedback_message,
                strategies=strategies,
            )

            if apply_critique:
                try:
                    critique_text = invoke_critique(
                        agent_config or {}, failed_result.content, feedback_message
                    )
                    feedback = format_critique_feedback(critique_text, feedback)
                    logger.info(
                        "LLM critique appended for %s (attempt %d)",
                        custom_id,
                        attempt + 1,
                    )
                except Exception:
                    logger.warning(
                        "LLM critique failed for %s, using un-critiqued feedback",
                        custom_id,
                        exc_info=True,
                    )

            original_user_content = original_record.get("user_content", "")
            original_record["user_content"] = f"{original_user_content}\n\n{feedback}"

            if "target_id" not in original_record:
                original_record["target_id"] = custom_id

            reprompt_records.append(original_record)

        if not reprompt_records:
            logger.debug("No records to reprompt")
            all_graduated.extend(still_failing)
            break

        try:
            from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

            reprompt_batch_name = f"{file_name}_reprompt_{attempt + 1}"
            preparator = BatchTaskPreparator(
                action_indices=action_indices,
                dependency_configs=dependency_configs,
                storage_backend=storage_backend,
            )
            prepared = preparator.prepare_tasks(
                agent_config=agent_config or {},
                data=reprompt_records,
                provider=provider,
                output_directory=output_directory,
                batch_name=reprompt_batch_name,
                source_data=source_data,
                attempt=attempt + 1,
            )

            batch_id, status = provider.submit_batch(
                tasks=prepared.tasks,
                batch_name=reprompt_batch_name,
                output_directory=output_directory,
            )

            logger.info(
                "Submitted reprompt batch %s with %d records",
                batch_id,
                len(prepared.tasks),
            )

            final_status = wait_for_batch_completion(
                provider, batch_id, total_items=len(prepared.tasks)
            )

            if final_status != BatchStatus.COMPLETED:
                logger.error(
                    "Reprompt batch %s did not complete: %s",
                    batch_id,
                    final_status,
                )
                _stamp_reprompt_failed(still_failing, reprompted_ids, validation_name)
                all_graduated.extend(still_failing)
                break

            reprompt_results = provider.retrieve_results(batch_id, output_directory)

            submitted_ids = {r.custom_id for r in still_failing}
            received_ids = BatchResultReconciler.collect_result_custom_ids(reprompt_results)
            dropped_ids = submitted_ids - received_ids

            if dropped_ids:
                logger.warning(
                    "Reprompt batch %s: provider dropped %d of %d records: %s",
                    batch_id,
                    len(dropped_ids),
                    len(submitted_ids),
                    sorted(dropped_ids),
                )
                dropped = [r for r in still_failing if r.custom_id in dropped_ids]
                _stamp_reprompt_failed(dropped, reprompted_ids, validation_name)
                all_graduated.extend(dropped)

            failing_map = {r.custom_id: r for r in still_failing}
            for reprompt_result in reprompt_results:
                if reprompt_result.custom_id in failing_map:
                    existing_recovery = failing_map[reprompt_result.custom_id].recovery_metadata

                    if not reprompt_result.recovery_metadata:
                        reprompt_result.recovery_metadata = RecoveryMetadata()

                    if existing_recovery and existing_recovery.retry:
                        reprompt_result.recovery_metadata.retry = existing_recovery.retry

            active_results = reprompt_results

        except Exception as e:
            if is_retriable_error(e):
                logger.warning("Transient error submitting reprompt batch: %s", e)
                _stamp_reprompt_failed(still_failing, reprompted_ids, validation_name)
                all_graduated.extend(still_failing)
                break
            logger.exception("Reprompt batch submission failed: %s", e)
            raise

    recovered_count = 0
    for r in all_graduated:
        if r.custom_id not in reprompted_ids:
            continue
        if r.recovery_metadata and r.recovery_metadata.reprompt:
            continue
        if not r.recovery_metadata:
            r.recovery_metadata = RecoveryMetadata()
        r.recovery_metadata.reprompt = RepromptMetadata(
            attempts=reprompted_ids[r.custom_id],
            passed=True,
            validation=validation_name,
        )
        recovered_count += 1

    if recovered_count:
        fire_event(
            RepromptRecoveredEvent(
                action_name=file_name,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                validation_name=validation_name,
            )
        )

    return all_graduated


def validate_results(
    results: list[BatchResult],
    agent_config: dict[str, Any] | None,
) -> tuple[list[BatchResult], str | None]:
    """Validate results using configured UDF without resubmitting.

    Args:
        results: Batch results to validate
        agent_config: Agent configuration with reprompt settings

    Returns:
        Tuple of (failed_results, validation_name).
        Empty failed_results means all passed.
        None validation_name means reprompt is not configured.
    """
    from agent_actions.processing.recovery.reprompt import parse_reprompt_config
    from agent_actions.processing.recovery.response_validator import safe_validate
    from agent_actions.processing.recovery.validation import get_validation_function

    raw_reprompt_config = (agent_config or {}).get("reprompt")
    parsed = parse_reprompt_config(raw_reprompt_config)
    if parsed is None:
        return [], None

    validation_name = parsed.validation_name

    _load_validation_udf(agent_config, raw_reprompt_config or {})

    try:
        validation_func, _ = get_validation_function(validation_name)
    except ValueError as e:
        logger.error("Failed to get validation function: %s", e)
        return [], None

    from agent_actions.processing.evaluation.strategies.validation import (
        detect_parse_error,
    )

    json_mode = bool((agent_config or {}).get("json_mode", get_default("json_mode")))

    failed_results = []
    for result in results:
        if not result.success:
            continue

        if (
            result.recovery_metadata
            and result.recovery_metadata.reprompt
            and result.recovery_metadata.reprompt.passed
        ):
            continue

        # Check parse error before UDF — matching online path
        if detect_parse_error(result.content, json_mode=json_mode):
            failed_results.append(result)
            continue

        is_valid = safe_validate(
            validation_func,
            result.content,
            context=result.custom_id,
            catch=(Exception,),
        )

        if not is_valid:
            failed_results.append(result)

    if not failed_results:
        logger.info("All %d results passed validation", len(results))

    return failed_results, validation_name


def submit_reprompt_batch(
    action_indices: dict[str, int],
    dependency_configs: dict[str, dict],
    storage_backend: "StorageBackend | None",
    provider: BaseBatchClient,
    failed_results: list[BatchResult],
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str,
    agent_config: dict[str, Any] | None,
    attempt: int,
) -> tuple[str, set[str]] | None:
    """Submit a reprompt batch for failed validation records without blocking.

    Returns the ids preparation actually admitted, which can be fewer than
    *failed_results*: the caller must carry the remainder forward itself rather
    than booking them as in flight. Returns None when there is nothing to submit.
    """
    from agent_actions.llm.batch.processing.preparator import (
        BatchTaskPreparator,
    )
    from agent_actions.processing.recovery.reprompt import parse_reprompt_config
    from agent_actions.processing.recovery.response_validator import (
        build_validation_feedback,
        resolve_feedback_strategies,
    )
    from agent_actions.processing.recovery.validation import get_validation_function

    raw_reprompt_config = (agent_config or {}).get("reprompt", {})
    parsed = parse_reprompt_config(raw_reprompt_config)
    if parsed is None:
        return None

    validation_name = parsed.validation_name
    strategies = resolve_feedback_strategies(raw_reprompt_config)

    try:
        _, feedback_message = get_validation_function(validation_name)
    except ValueError as e:
        logger.error("Failed to get validation function for reprompt: %s", e)
        return None

    reprompt_records = []
    for failed_result in failed_results:
        custom_id = failed_result.custom_id
        if custom_id not in context_map:
            raise RuntimeError(
                f"Cannot reprompt {custom_id}: absent from the context map for "
                f"{file_name}. The record failed validation, so it was built from that "
                "map — its absence means the map and the results have diverged, and "
                "reprompting the rest would leave this record with no output row."
            )

        original_record = context_map[custom_id].copy()

        feedback = build_validation_feedback(
            failed_response=failed_result.content,
            feedback_message=feedback_message,
            strategies=strategies,
        )

        original_user_content = original_record.get("user_content", "")
        original_record["user_content"] = f"{original_user_content}\n\n{feedback}"

        if "target_id" not in original_record:
            original_record["target_id"] = custom_id

        reprompt_records.append(original_record)

    if not reprompt_records:
        logger.debug("No records to reprompt")
        return None

    try:
        reprompt_batch_name = f"{file_name}_reprompt_{attempt}"
        preparator = BatchTaskPreparator(
            action_indices=action_indices,
            dependency_configs=dependency_configs,
            storage_backend=storage_backend,
        )
        source_data = _load_source_data_for_reprompt(storage_backend)
        prepared = preparator.prepare_tasks(
            agent_config=agent_config or {},
            data=reprompt_records,
            provider=provider,
            output_directory=output_directory,
            batch_name=reprompt_batch_name,
            source_data=source_data,
            attempt=attempt,
        )

        batch_id, _ = provider.submit_batch(
            tasks=prepared.tasks,
            batch_name=reprompt_batch_name,
            output_directory=output_directory,
        )

        submitted_ids = {
            str(custom_id)
            for custom_id, row in (prepared.context_map or {}).items()
            if BatchContextMetadata.is_included(row)
        }
        logger.info(
            "Async reprompt batch submitted: %s with %d records (attempt %d)",
            batch_id,
            len(submitted_ids),
            attempt,
        )
        return (batch_id, submitted_ids)

    except Exception as e:
        logger.exception("Error submitting reprompt batch: %s", e)
        return None


def process_reprompt_results(
    reprompt_results: list[BatchResult],
    accumulated_results: list[BatchResult],
) -> list[BatchResult]:
    """Merge reprompt results into accumulated results (override by custom_id).

    Args:
        reprompt_results: New results from reprompt batch
        accumulated_results: Previously accumulated results

    Returns:
        Merged results with reprompt results replacing originals by custom_id
    """
    result_map = {r.custom_id: r for r in accumulated_results}

    for reprompt_result in reprompt_results:
        if reprompt_result.custom_id in result_map:
            existing_recovery = result_map[reprompt_result.custom_id].recovery_metadata
            if not reprompt_result.recovery_metadata:
                reprompt_result.recovery_metadata = RecoveryMetadata()
            if existing_recovery and existing_recovery.retry:
                reprompt_result.recovery_metadata.retry = existing_recovery.retry

        result_map[reprompt_result.custom_id] = reprompt_result

    return list(result_map.values())
