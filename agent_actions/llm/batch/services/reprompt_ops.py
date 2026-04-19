"""Reprompt and validation operations for batch result quality assurance."""

import logging
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.services.retry_polling import (
    import_validation_module,
    wait_for_batch_completion,
)
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.processing.types import RecoveryMetadata

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


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


def validate_and_reprompt(
    action_indices: dict[str, int],
    dependency_configs: dict[str, dict],
    storage_backend: "StorageBackend | None",
    results: list[BatchResult],
    provider: BaseBatchClient,
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str | None,
    agent_config: dict[str, Any] | None,
) -> list[BatchResult]:
    """Validate results and reprompt failures with feedback."""
    from agent_actions.processing.recovery.reprompt import parse_reprompt_config
    from agent_actions.processing.recovery.response_validator import (
        build_validation_feedback,
        resolve_feedback_strategies,
        safe_validate,
    )
    from agent_actions.processing.recovery.validation import get_validation_function
    from agent_actions.processing.types import RepromptMetadata

    raw_reprompt_config = (agent_config or {}).get("reprompt")
    parsed = parse_reprompt_config(raw_reprompt_config)
    logger.debug(
        "Batch reprompt check: agent_config has %d keys, parsed=%s",
        len(agent_config or {}),
        parsed,
    )
    if parsed is None:
        logger.debug("Reprompt not configured, skipping validation")
        return results

    validation_name = parsed.validation_name
    max_attempts = parsed.max_attempts
    on_exhausted = parsed.on_exhausted
    strategies = resolve_feedback_strategies(raw_reprompt_config)

    _load_validation_udf(agent_config, raw_reprompt_config or {})

    try:
        validation_func, feedback_message = get_validation_function(validation_name)
    except ValueError as e:
        logger.error("Failed to get validation function: %s", e)
        return results

    reprompt_attempts: dict[str, int] = {}
    validation_status: dict[str, bool] = {}
    result_map = {r.custom_id: r for r in results}

    attempt = 0
    while attempt < max_attempts:
        attempt += 1

        failed_results = []
        for result in result_map.values():
            if not result.success:
                continue

            if (
                result.recovery_metadata
                and result.recovery_metadata.reprompt
                and result.recovery_metadata.reprompt.passed
            ):
                continue

            is_valid = safe_validate(
                validation_func,
                result.content,
                context=result.custom_id,
                catch=(Exception,),
            )

            validation_status[result.custom_id] = is_valid

            if not is_valid:
                failed_results.append(result)

        if not failed_results:
            logger.info("All %d records passed validation", len(result_map))
            break

        logger.warning(
            "Reprompt attempt %d/%d: %d records failed validation",
            attempt,
            max_attempts,
            len(failed_results),
        )

        for failed_result in failed_results:
            reprompt_attempts[failed_result.custom_id] = (
                reprompt_attempts.get(failed_result.custom_id, 0) + 1
            )

        if attempt >= max_attempts:
            if on_exhausted == "raise" and failed_results:
                raise RuntimeError(
                    f"Reprompt validation exhausted for {failed_results[0].custom_id} "
                    f"after {attempt} attempts (validation: {validation_name})"
                )
            break

        use_critique = (raw_reprompt_config or {}).get("use_llm_critique", False)
        critique_after = (raw_reprompt_config or {}).get("critique_after_attempt", 2)
        apply_critique = use_critique and attempt >= critique_after and attempt < max_attempts

        if apply_critique:
            from agent_actions.processing.recovery.critique import (
                format_critique_feedback,
                invoke_critique,
            )

            if len(failed_results) > 10:
                logger.warning(
                    "Critique enabled for %d failed records — each requires a "
                    "synchronous LLM call, expect increased latency",
                    len(failed_results),
                )

        reprompt_records = []
        for failed_result in failed_results:
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
                        attempt,
                    )
                except Exception:
                    logger.warning(
                        "Critique failed for %s, continuing without",
                        custom_id,
                        exc_info=True,
                    )

            original_user_content = original_record.get("user_content", "")
            original_record["user_content"] = f"{original_user_content}\n\n{feedback}"

            if "target_id" not in original_record:
                original_record["target_id"] = custom_id

            reprompt_records.append(original_record)

        if not reprompt_records:
            logger.warning("No records to reprompt")
            break

        try:
            from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

            reprompt_batch_name = f"{file_name or 'batch'}_reprompt_{attempt}"
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
                break

            reprompt_results = provider.retrieve_results(batch_id, output_directory)

            for reprompt_result in reprompt_results:
                if reprompt_result.custom_id in result_map:
                    existing_recovery = result_map[reprompt_result.custom_id].recovery_metadata

                    if not reprompt_result.recovery_metadata:
                        reprompt_result.recovery_metadata = RecoveryMetadata()

                    if existing_recovery and existing_recovery.retry:
                        reprompt_result.recovery_metadata.retry = existing_recovery.retry

                result_map[reprompt_result.custom_id] = reprompt_result

        except Exception as e:
            logger.exception("Error during reprompt batch submission: %s", e)
            break

    for custom_id, attempts in reprompt_attempts.items():
        if custom_id in result_map:
            result = result_map[custom_id]
            passed = validation_status.get(custom_id, False)

            if not result.recovery_metadata:
                result.recovery_metadata = RecoveryMetadata()

            result.recovery_metadata.reprompt = RepromptMetadata(
                attempts=attempts,
                passed=passed,
                validation=validation_name,
            )

    return list(result_map.values())


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
    file_name: str | None,
    agent_config: dict[str, Any] | None,
    attempt: int,
) -> tuple[str, int] | None:
    """Submit a reprompt batch for failed validation records without blocking.

    Args:
        action_indices: Agent name to node index mapping
        dependency_configs: Dependency configurations
        storage_backend: Optional storage backend
        provider: Batch API client
        failed_results: Results that failed validation
        context_map: Context map for record lookup
        output_directory: Output directory path
        file_name: Original file name
        agent_config: Agent configuration
        attempt: Current reprompt attempt number

    Returns:
        Tuple of (batch_id, record_count) if submitted, None if nothing to submit
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
            logger.warning("Cannot reprompt %s: not found in context_map", custom_id)
            continue

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
        logger.warning("No records to reprompt")
        return None

    try:
        reprompt_batch_name = f"{file_name or 'batch'}_reprompt_{attempt}"
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
        )

        batch_id, _ = provider.submit_batch(
            tasks=prepared.tasks,
            batch_name=reprompt_batch_name,
            output_directory=output_directory,
        )

        logger.info(
            "Async reprompt batch submitted: %s with %d records (attempt %d)",
            batch_id,
            len(prepared.tasks),
            attempt,
        )
        return (batch_id, len(prepared.tasks))

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


def apply_exhausted_reprompt_metadata(
    results: list[BatchResult],
    failed_ids: set[str],
    validation_name: str,
    attempt: int,
    on_exhausted: str,
) -> list[BatchResult]:
    """Apply reprompt exhaustion metadata to failed records.

    Mutates results in-place (sets recovery_metadata on individual items)
    and returns the same list for convenience.

    Args:
        results: All accumulated results (mutated in-place)
        failed_ids: IDs that still fail validation
        validation_name: Name of the validation UDF
        attempt: Number of attempts made
        on_exhausted: Policy — "return_last" or "raise"

    Returns:
        The same results list with exhaustion metadata applied

    Raises:
        RuntimeError: If on_exhausted == "raise"
    """
    from agent_actions.processing.types import RepromptMetadata

    for result in results:
        if result.custom_id not in failed_ids:
            continue

        if on_exhausted == "raise":
            raise RuntimeError(
                f"Reprompt validation exhausted for {result.custom_id} "
                f"after {attempt} attempts (validation: {validation_name})"
            )

        if not result.recovery_metadata:
            result.recovery_metadata = RecoveryMetadata()

        result.recovery_metadata.reprompt = RepromptMetadata(
            attempts=attempt,
            passed=False,
            validation=validation_name,
        )

    return results
