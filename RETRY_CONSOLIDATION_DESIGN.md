# Retry Exhaustion Consolidation: Online & Batch Unified Design

## Overview
**Problem:** Online and batch modes handle `on_exhausted="raise"` differently
- **Online:** Exception swallowed, record lost
- **Batch:** Explicit handling, record preserved with metadata

**Solution:** Consolidate to unified approach where both modes:
1. Create EXHAUSTED result records with metadata
2. Check `on_exhausted` config at aggregation layer only
3. Either include in output (return_last) or raise exception (raise)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    UNIFIED FLOW (Both Modes)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  RetryService.execute()                                         │
│  ├─ on_exhausted="raise": Returns exhausted=True (NO RAISE!)   │
│  └─ on_exhausted="return_last": Returns exhausted=True         │
│                    ↓                                             │
│  RecordProcessor._execute_llm()                                 │
│  ├─ Returns: executed=False, response=None                      │
│  ├─ NO exception handling (exception propagates or caught next) │
│  ├─ Tracks recovery_metadata with retry info                   │
│  └─ Does NOT check on_exhausted config                         │
│                    ↓                                             │
│  RecordProcessor.process()                                      │
│  ├─ Returns: ProcessingResult(status=EXHAUSTED)                │
│  ├─ NO try/catch for retry exceptions                          │
│  ├─ Includes recovery_metadata                                 │
│  └─ Does NOT check on_exhausted config                         │
│                    ↓                                             │
│  RecordProcessor.process_batch()                                │
│  ├─ NO exception swallowing for retry exhaustion               │
│  ├─ ConfigurationError still re-raised (breaks workflow)       │
│  └─ Collects ALL results including EXHAUSTED status            │
│                    ↓                                             │
│   ┌─────────────────┴──────────────────┐                       │
│   │                                     │                        │
│   ▼ ONLINE                              ▼ BATCH                 │
│   TargetGenerator                       BatchResultProcessor    │
│   ._process_by_strategy()               ._stage_6_merge_...()  │
│   (Aggregation Layer)                   (Aggregation Layer)    │
│   │                                     │                        │
│   ├─ Iterate results                   ├─ Iterate passthrough  │
│   ├─ If EXHAUSTED:                     ├─ If exhausted:        │
│   │  ├─ Check on_exhausted config      │  ├─ Check on_exhausted
│   │  ├─ Log exhaustion                 │  ├─ Log exhaustion    │
│   │  └─ IF raise: ↓ Raise              │  └─ IF raise: ↓ Raise │
│   │  ELSE: ↓ Add to output             │  ELSE: ↓ Add to output│
│   │                                     │                        │
│   └─ Write output file                  └─ Write output file    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pseudocode

### 1. RetryService.execute() [CHANGE: Don't raise immediately]

```python
# File: agent_actions/core/retry_service.py

def execute(
    self,
    operation: Callable[[], T],
    context: Optional[str] = None,
) -> RetryResult:
    """
    Execute operation with retry on transient failures.

    UNIFIED BEHAVIOR:
    - on_exhausted="raise" or "return_last" both return exhausted=True
    - Caller decides whether to raise or include in output
    - This enables unified handling in both online and batch modes
    """
    last_response = None
    last_error: Optional[Exception] = None
    reason: Optional[str] = None

    for attempt in range(1, self.max_attempts + 1):
        try:
            response = operation()
            # Success - return immediately
            return RetryResult(
                response=response,
                attempts=attempt,
                reason=reason,
                exhausted=False,
                last_error=str(last_error) if last_error else None,
            )

        except Exception as e:
            last_error = e
            reason = classify_error(e)
            last_response = None

            if is_retriable_error(e):
                # Transient error - may retry
                log_context = f" ({context})" if context else ""

                if attempt < self.max_attempts:
                    # Still have attempts left - retry
                    logger.info(
                        "Retry attempt %d/%d%s: %s - %s",
                        attempt,
                        self.max_attempts,
                        log_context,
                        reason,
                        str(e),
                    )
                    # Continue loop to retry
                    continue
                else:
                    # Exhausted retries
                    logger.warning(
                        "Retry exhausted after %d attempts%s: %s - %s",
                        attempt,
                        log_context,
                        reason,
                        str(e),
                    )
                    # Fall through to exhausted handling below
            else:
                # Non-retriable error - fail immediately without retry
                logger.error(
                    "Non-retriable error%s: %s",
                    f" ({context})" if context else "",
                    str(e),
                )
                # ⚠️ CHANGE: Don't raise here - let caller handle
                # This allows unified on_exhausted handling
                break  # Exit loop with last_error set

    # UNIFIED EXHAUSTED HANDLING
    # Return result with exhausted=True regardless of on_exhausted config
    # The config is checked at aggregation layer (online/batch)
    return RetryResult(
        response=last_response,
        attempts=self.max_attempts,
        reason=reason,
        exhausted=True,  # ← Always set to True
        last_error=str(last_error) if last_error else None,
    )
```

### 2. RecordProcessor._execute_llm() [CHANGE: No exception propagation]

```python
# File: agent_actions/core/record_processor.py

def _execute_llm(
    self,
    content: Any,
    prep_result,
    context: ProcessingContext
) -> Tuple[Any, bool, Dict, Optional[RecoveryMetadata]]:
    """
    Execute LLM with optional retry and reprompt.

    UNIFIED BEHAVIOR:
    - Returns executed=False for exhausted retries
    - Does NOT raise exceptions from retry exhaustion
    - Tracks recovery_metadata for all recovery attempts
    - Caller decides what to do with EXHAUSTED status
    """
    from agent_actions.utilities.processor.processor_helpers import (
        run_dynamic_agent,
    )
    from agent_actions.core.reprompt_service import create_reprompt_service_from_config

    tools_path = context.agent_config.get("tools", {}).get("path")
    retry_config = context.agent_config.get("retry")
    reprompt_config = context.agent_config.get("reprompt")

    retry_service = create_retry_service_from_config(retry_config)
    reprompt_service = create_reprompt_service_from_config(reprompt_config)

    recovery_metadata = RecoveryMetadata()

    # ===== BRANCH 1: Reprompt + Retry =====
    if reprompt_service and retry_service:
        logger.debug(
            f"[{context.agent_name}] Executing with both reprompt and retry protection",
            extra={"action": context.agent_name, "mode": "reprompt+retry"}
        )

        def llm_with_retry(prompt: str):
            """LLM execution wrapped with retry protection."""
            def llm_call():
                return run_dynamic_agent(
                    context.agent_config,
                    context.agent_name,
                    content,
                    prompt,
                    tools_path=tools_path,
                    llm_context=prep_result.llm_context,
                )

            retry_result = retry_service.execute(
                llm_call,
                context=f"action={context.agent_name}",
            )

            # Track retry metadata if retried
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

                logger.info(
                    f"[{context.agent_name}] Retry result: attempts={retry_result.attempts}, "
                    f"exhausted={retry_result.exhausted}, reason={retry_result.reason}",
                    extra={
                        "action": context.agent_name,
                        "attempts": retry_result.attempts,
                        "exhausted": retry_result.exhausted,
                        "reason": retry_result.reason,
                    }
                )

            # Return None if exhausted (signals caller to handle)
            if retry_result.exhausted:
                return None, False

            # Return response if succeeded
            return retry_result.response

        # Execute with reprompt (wraps retry)
        reprompt_result = reprompt_service.execute(
            llm_operation=llm_with_retry,
            original_prompt=prep_result.formatted_prompt,
            context=f"action={context.agent_name}",
        )

        # Track reprompt metadata if attempted
        if reprompt_result.attempts > 1:
            recovery_metadata.reprompt = RepromptMetadata(
                attempts=reprompt_result.attempts,
                passed=reprompt_result.passed,
                validation=reprompt_result.validation_name,
            )

            logger.info(
                f"[{context.agent_name}] Reprompt result: attempts={reprompt_result.attempts}, "
                f"passed={reprompt_result.passed}, validation={reprompt_result.validation_name}",
                extra={
                    "action": context.agent_name,
                    "reprompt_attempts": reprompt_result.attempts,
                    "reprompt_passed": reprompt_result.passed,
                    "validation_udf": reprompt_result.validation_name,
                }
            )

        if reprompt_result.exhausted:
            logger.warning(
                f"[{context.agent_name}] Reprompt exhausted after {reprompt_result.attempts} attempts",
                extra={
                    "action": context.agent_name,
                    "reprompt_exhausted": True,
                    "attempts": reprompt_result.attempts,
                }
            )

        return (
            reprompt_result.response,
            reprompt_result.executed,
            prep_result.passthrough_fields,
            recovery_metadata if not recovery_metadata.is_empty() else None,
        )

    # ===== BRANCH 2: Retry Only =====
    elif retry_service:
        logger.debug(
            f"[{context.agent_name}] Executing with retry protection only",
            extra={"action": context.agent_name, "mode": "retry"}
        )

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

        # Track retry metadata if retried
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

            logger.info(
                f"[{context.agent_name}] Retry result: attempts={retry_result.attempts}, "
                f"exhausted={retry_result.exhausted}, reason={retry_result.reason}",
                extra={
                    "action": context.agent_name,
                    "attempts": retry_result.attempts,
                    "exhausted": retry_result.exhausted,
                    "reason": retry_result.reason,
                }
            )

        # UNIFIED: Return executed=False when exhausted
        if retry_result.exhausted:
            logger.warning(
                f"[{context.agent_name}] Retry exhausted after {retry_result.attempts} attempts: {retry_result.last_error}",
                extra={
                    "action": context.agent_name,
                    "retry_exhausted": True,
                    "attempts": retry_result.attempts,
                    "last_error": retry_result.last_error,
                }
            )
            return (
                None,  # response
                False,  # executed=False (signals EXHAUSTED status)
                prep_result.passthrough_fields,
                recovery_metadata,  # Include retry metadata
            )

        # Success: unpack and return
        response, executed = retry_result.response
        return (
            response,
            executed,
            prep_result.passthrough_fields,
            recovery_metadata if not recovery_metadata.is_empty() else None,
        )

    # ===== BRANCH 3: No retry =====
    else:
        logger.debug(
            f"[{context.agent_name}] Executing without retry protection",
            extra={"action": context.agent_name, "mode": "direct"}
        )
        response, executed = run_dynamic_agent(
            context.agent_config,
            context.agent_name,
            content,
            prep_result.formatted_prompt,
            tools_path=tools_path,
            llm_context=prep_result.llm_context,
        )
        return response, executed, prep_result.passthrough_fields, None
```

### 3. RecordProcessor.process() [CHANGE: Returns EXHAUSTED status]

```python
# File: agent_actions/core/record_processor.py

def process(
    self,
    item: Any,
    context: ProcessingContext
) -> ProcessingResult:
    """
    Process single item with unified exhaustion handling.

    UNIFIED BEHAVIOR:
    - Returns ProcessingResult with status=EXHAUSTED when retry exhausted
    - Does NOT raise exceptions from retry exhaustion
    - on_exhausted check deferred to aggregation layer
    """
    # Step 1-4: Early guard, prompt prep (unchanged)
    content, source_guid, source_snapshot = self._normalize_input(item, context)
    guard_result = self._evaluate_guard(content, source_guid, context)
    if guard_result is not None:
        return guard_result

    if context.is_first_stage:
        source_content = content
    else:
        source_content = self._get_source_content(source_guid, context)

    current_item = item if isinstance(item, dict) else None
    prep_result = self._prepare_prompt(content, source_content, context, current_item)

    # Step 5: Execute LLM (with optional retry)
    response, executed, passthrough_fields, recovery_metadata = self._execute_llm(
        content, prep_result, context
    )

    # Step 6: Handle non-execution
    if not executed:
        if response is None:
            # Check if this is retry exhaustion vs guard filter
            if recovery_metadata and recovery_metadata.retry:
                # === UNIFIED: Return EXHAUSTED result ===
                logger.warning(
                    f"[{context.agent_name}] Record {source_guid} retry exhausted "
                    f"after {recovery_metadata.retry.attempts} attempts (will handle at aggregation layer)",
                    extra={
                        "action": context.agent_name,
                        "source_guid": source_guid,
                        "exhausted": True,
                        "attempts": recovery_metadata.retry.attempts,
                        "reason": recovery_metadata.retry.reason,
                    }
                )
                return ProcessingResult(
                    status=ProcessingStatus.EXHAUSTED,
                    source_guid=source_guid,
                    error=f"Retry exhausted after {recovery_metadata.retry.attempts} attempts",
                    recovery_metadata=recovery_metadata,
                    source_snapshot=source_snapshot,
                )

            # Guard filter (not retry exhaustion)
            return ProcessingResult.filtered(
                source_guid=source_guid,
                source_snapshot=source_snapshot,
            )

        # Guard skip
        return ProcessingResult.skipped(
            passthrough_data=response,
            reason="guard_skip",
            source_guid=source_guid,
            passthrough_fields=passthrough_fields,
            source_snapshot=source_snapshot,
        )

    # Step 7-9: Transform, enrich, return (unchanged)
    transformed = self._transform_response(
        response, content, source_guid, passthrough_fields, context
    )
    result = ProcessingResult.success(
        data=transformed,
        source_guid=source_guid,
        passthrough_fields=passthrough_fields,
        source_snapshot=source_snapshot,
        raw_response=response,
        recovery_metadata=recovery_metadata,
    )
    return self.enrichment_pipeline.enrich(result, context)
```

### 4. RecordProcessor.process_batch() [CHANGE: No exception swallowing]

```python
# File: agent_actions/core/record_processor.py

def process_batch(
    self,
    items: List[Any],
    context: ProcessingContext
) -> List[ProcessingResult]:
    """
    Process multiple records without swallowing exhaustion exceptions.

    UNIFIED BEHAVIOR:
    - Collects all results including EXHAUSTED status
    - Does NOT swallow exceptions from retry exhaustion
    - ConfigurationError still raises (breaks workflow)
    - Defers on_exhausted decision to aggregation layer
    """
    results = []

    for idx, item in enumerate(items):
        try:
            item_context = self._create_item_context(context, idx, item)

            logger.debug(
                f"[{context.agent_name}] Processing item {idx}/{len(items)}",
                extra={
                    "action": context.agent_name,
                    "item_index": idx,
                    "total_items": len(items),
                }
            )

            result = self.process(item, item_context)
            results.append(result)

            # Log result status
            logger.debug(
                f"[{context.agent_name}] Item {idx} result: {result.status.value}",
                extra={
                    "action": context.agent_name,
                    "item_index": idx,
                    "status": result.status.value,
                    "source_guid": result.source_guid,
                }
            )

        except ConfigurationError:
            # Configuration errors break the entire workflow
            logger.error(
                f"[{context.agent_name}] Configuration error at item {idx} - workflow cannot continue",
                extra={
                    "action": context.agent_name,
                    "item_index": idx,
                    "error_type": "ConfigurationError",
                }
            )
            raise

        # ⚠️ REMOVED: Exception handling for retry exhaustion
        # We now return EXHAUSTED status instead of raising
        # This allows unified handling at aggregation layer

    logger.info(
        f"[{context.agent_name}] Batch processing complete: {len(results)} items processed",
        extra={
            "action": context.agent_name,
            "total_items": len(results),
            "success": sum(1 for r in results if r.status == ProcessingStatus.SUCCESS),
            "skipped": sum(1 for r in results if r.status == ProcessingStatus.SKIPPED),
            "filtered": sum(1 for r in results if r.status == ProcessingStatus.FILTERED),
            "failed": sum(1 for r in results if r.status == ProcessingStatus.FAILED),
            "exhausted": sum(1 for r in results if r.status == ProcessingStatus.EXHAUSTED),
        }
    )

    return results
```

### 5. TargetGenerator._process_by_strategy() [NEW: Aggregation layer]

```python
# File: agent_actions/orchestration/target_generator.py

def _process_by_strategy(
    self,
    data: Any,
    file_path: str,
    base_directory: str,
    output_directory: str,
):
    """
    Process data and handle aggregation with unified on_exhausted handling.

    UNIFIED BEHAVIOR:
    - Both online and batch defer on_exhausted checks to aggregation layer
    - Aggregation layer has full visibility of all results
    - Can make global decision: fail action vs include exhausted records
    """
    # ... setup context, source_data, etc (unchanged) ...

    # Process records
    if self.granularity == "file" and self.is_tool_action:
        results = self._process_file_mode_tool(data, context)
    else:
        results = self.record_processor.process_batch(data, context)

    # ===== UNIFIED AGGREGATION LAYER =====
    # Check for exhausted records and respect on_exhausted config

    exhausted_results = [r for r in results if r.status == ProcessingStatus.EXHAUSTED]

    if exhausted_results:
        # Get on_exhausted config from agent
        retry_config = self.config.agent_config.get("retry", {})
        on_exhausted = retry_config.get("on_exhausted", "return_last")

        logger.warning(
            f"[{self.config.agent_name}] {len(exhausted_results)} records have exhausted retries "
            f"(on_exhausted={on_exhausted})",
            extra={
                "action": self.config.agent_name,
                "exhausted_count": len(exhausted_results),
                "total_records": len(results),
                "on_exhausted": on_exhausted,
            }
        )

        if on_exhausted == "raise":
            # Fail the action immediately
            exhausted_record = exhausted_results[0]
            error_message = (
                f"Retry exhausted for record {exhausted_record.source_guid}: "
                f"{exhausted_record.error}"
            )

            logger.error(
                f"[{self.config.agent_name}] Failing action due to on_exhausted='raise'",
                extra={
                    "action": self.config.agent_name,
                    "on_exhausted": "raise",
                    "error": error_message,
                    "exhausted_records": len(exhausted_results),
                }
            )

            raise AgentActionsException(
                error_message,
                context={
                    "agent_name": self.config.agent_name,
                    "exhausted_records": len(exhausted_results),
                    "on_exhausted": "raise",
                }
            )

    # === UNIFIED: Add exhausted records to output (on_exhausted="return_last") ===
    output = []
    for result in results:
        if result.status == ProcessingStatus.SUCCESS:
            output.extend(result.data)
        elif result.status == ProcessingStatus.SKIPPED:
            output.extend(result.data)
        elif result.status == ProcessingStatus.EXHAUSTED:
            # ← NEW: Include exhausted records with empty schema + _recovery
            exhausted_item = self._create_exhausted_record(result)
            output.extend(exhausted_item)

            logger.info(
                f"[{self.config.agent_name}] Added exhausted record to output with metadata",
                extra={
                    "action": self.config.agent_name,
                    "source_guid": result.source_guid,
                    "exhausted": True,
                    "on_exhausted": "return_last",
                }
            )
        elif result.status == ProcessingStatus.FAILED:
            logger.error(
                f"[{self.config.agent_name}] Failed to process record {result.source_guid}: {result.error}",
                extra={
                    "action": self.config.agent_name,
                    "source_guid": result.source_guid,
                    "status": "failed",
                }
            )

    # Write output
    logger.info(
        f"[{self.config.agent_name}] Writing output: {len(output)} records",
        extra={
            "action": self.config.agent_name,
            "output_count": len(output),
            "file_path": str(file_path),
        }
    )

    self.output_handler.save_main_output(output, file_path, base_directory, output_directory)


def _create_exhausted_record(self, result: ProcessingResult) -> List[Dict]:
    """
    Create output record for exhausted retry item.

    Matches batch mode behavior:
    - Empty schema fields
    - _recovery metadata with retry info
    - Preserved source_guid and lineage
    """
    if not result.recovery_metadata or not result.recovery_metadata.retry:
        return []

    # Get schema from config to create empty fields
    empty_content = {}
    schema = self.config.agent_config.get("schema", {})
    if isinstance(schema, dict):
        properties = schema.get("properties", {})
        for field_name, field_spec in properties.items():
            field_type = field_spec.get("type", "string")
            if field_type == "array":
                empty_content[field_name] = []
            elif field_type == "object":
                empty_content[field_name] = {}
            elif field_type == "boolean":
                empty_content[field_name] = False
            elif field_type in ("number", "integer"):
                empty_content[field_name] = 0
            else:
                empty_content[field_name] = None

    # Build exhausted record
    exhausted_record = {
        "source_guid": result.source_guid,
        "content": empty_content,
        "metadata": {"retry_exhausted": True},
        "_recovery": result.recovery_metadata.to_dict(),
    }

    return [exhausted_record]
```

### 6. BatchResultProcessor._stage_6_merge_passthroughs() [SIMPLIFIED: Same logic]

```python
# File: agent_actions/llm_invocation/batch/processing/batch_result_processor.py

def _stage_6_merge_passthroughs(
    self,
    ctx: BatchProcessingContext
) -> BatchProcessingContext:
    """
    Merge passthrough and exhausted records using same unified logic as online.

    UNIFIED BEHAVIOR:
    - Both online and batch check on_exhausted at aggregation layer
    - If "raise": Exception raised (caught by caller)
    - If "return_last": Exhausted record created and added to output
    """
    reconciliation = ctx.reconciler.reconcile()

    if reconciliation.passthrough_records:
        builder = BatchPassthroughBuilder(ctx.output_directory)

        for custom_id, original_row in reconciliation.passthrough_records:
            is_exhausted = ctx.exhausted_recovery and custom_id in ctx.exhausted_recovery

            if is_exhausted:
                # Get on_exhausted config
                on_exhausted = "return_last"  # default
                if ctx.agent_config:
                    retry_config = ctx.agent_config.get("retry", {})
                    on_exhausted = retry_config.get("on_exhausted", "return_last")

                logger.warning(
                    f"[{ctx.agent_config.get('agent_type')}] Record {custom_id} exhausted "
                    f"(on_exhausted={on_exhausted})",
                    extra={
                        "action": ctx.agent_config.get("agent_type"),
                        "custom_id": custom_id,
                        "on_exhausted": on_exhausted,
                    }
                )

                if on_exhausted == "raise":
                    # Fail the batch action
                    recovery_meta = ctx.exhausted_recovery[custom_id]
                    error_message = (
                        f"Retry exhausted for record {custom_id} after "
                        f"{recovery_meta.retry.attempts} attempts (on_exhausted=raise)"
                    )

                    logger.error(
                        f"[{ctx.agent_config.get('agent_type')}] Failing action due to on_exhausted='raise'",
                        extra={
                            "action": ctx.agent_config.get("agent_type"),
                            "on_exhausted": "raise",
                            "custom_id": custom_id,
                            "error": error_message,
                        }
                    )

                    raise RuntimeError(error_message)

                # on_exhausted == "return_last": Create exhausted item
                recovery_meta = ctx.exhausted_recovery[custom_id]
                exhausted_item = self._create_exhausted_item(
                    ctx, custom_id, original_row, recovery_meta
                )
                ctx.processed_data.append(exhausted_item)
                ctx.error_count += 1

                logger.info(
                    f"[{ctx.agent_config.get('agent_type')}] Added exhausted record to output",
                    extra={
                        "action": ctx.agent_config.get("agent_type"),
                        "custom_id": custom_id,
                        "on_exhausted": "return_last",
                    }
                )

            else:
                # Regular passthrough (guard skip)
                reason = "conditional_clause_failed"
                passthrough_item = builder._build_item(original_row, reason, custom_id)
                passthrough_item.pop(ContextMetaKeys.FILTER_STATUS, None)
                ctx.processed_data.append(passthrough_item)
                ctx.passthrough_count += 1

    return ctx
```

### 7. Exception Flow [UNIFIED]

```python
# Both online and batch follow same exception path

# Online: TargetGenerator._process_by_strategy()
if on_exhausted == "raise":
    raise AgentActionsException(...)
    ↓
# Caught by: target_generator.process() line 237-258
except (AgentActionsException, ConfigurationError, ValueError) as e:
    raise AgentActionsException(...) from e

# Batch: BatchProcessingService._process_single_batch_file()
if on_exhausted == "raise":
    raise RuntimeError(...) from BatchResultProcessor._stage_6_merge_passthroughs()
    ↓
# Caught by: process_batch_results() line 93-154
except ProcessingError:
    raise
except Exception as e:
    raise ProcessingError(...) from e

# OR Batch: BatchProcessingService.process_all_batch_results()
if on_exhausted == "raise":
    raise RuntimeError(...) from BatchResultProcessor._stage_6_merge_passthroughs()
    ↓
# Caught by: process_all_batch_results() line 189-215
except Exception as e:
    logger.exception(...)
    continue  # Swallowed per current design
```

### 8. Logging Strategy [UNIFIED]

```
LEVEL          MESSAGE LOCATION                    CONTEXT
═════════════════════════════════════════════════════════════════════════

DEBUG:
├─ Record start         RecordProcessor.process_batch()     item_index, action
├─ Execution mode       _execute_llm()                      mode (direct/retry/...)
└─ Item result          process_batch()                     status, source_guid

INFO:
├─ Retry result         _execute_llm()                      attempts, exhausted, reason
├─ Reprompt result      _execute_llm()                      attempts, passed, validation
├─ Batch complete       process_batch()                     success/skipped/filtered/failed/exhausted counts
├─ Exhausted count      Aggregation layer                   exhausted_count, on_exhausted
├─ Exhausted record     Aggregation layer                   source_guid, on_exhausted value
└─ Output written       Aggregation layer                   output_count, file_path

WARNING:
├─ Retry exhausted      _execute_llm()                      attempts, reason, last_error
├─ Reprompt exhausted   _execute_llm()                      attempts
├─ Multiple exhausted   Aggregation layer                   count, on_exhausted config
└─ Batch retry exhausted BatchProcessingService             missing_ids count, retry_attempts

ERROR:
├─ Non-retriable err    RetryService.execute()              error type, context
├─ Record processing    process_batch() exception handler   item_index, error
├─ Config error         process_batch()                     config details
├─ Raise handling       Aggregation layer                   error_message, on_exhausted
├─ Failed record        Output collection                   source_guid, error
└─ Batch processing     BatchProcessingService              batch_id, error

EXTRA FIELDS (for structured logging):
{
  "action": agent_name,
  "source_guid": source_guid,
  "status": ProcessingStatus,
  "attempts": retry_attempts,
  "exhausted": bool,
  "on_exhausted": "raise" | "return_last",
  "reason": retry_reason,
  "mode": "online" | "batch",
  ...
}
```

---

## Key Changes Summary

| Component | Current | Proposed | Benefit |
|-----------|---------|----------|---------|
| RetryService.execute() | Raises on exhaustion | Returns exhausted=True | Unified handling at aggregation layer |
| _execute_llm() | Propagates exception | Returns executed=False | No exceptions escape recovery logic |
| process() | N/A | Returns EXHAUSTED status | Consistent result types |
| process_batch() | Swallows retry exceptions | No try/catch for retry | All results flow through aggregation |
| Aggregation Point | N/A (online) | Both online/batch | Single place for on_exhausted decision |
| Output Records | Lost when exhausted | Created with metadata | Data integrity preserved |
| Error Visibility | Generic "Error processing" | Specific exhaustion details | Better debugging |
| Logging | Scattered | Centralized with extra fields | Better observability |

---

## Implementation Order

1. **Phase 1: Foundational**
   - Update RetryService.execute() to not raise on exhaustion
   - Update _execute_llm() to return executed=False for all exhaustion paths
   - Update process() to return EXHAUSTED status

2. **Phase 2: Online Mode**
   - Remove try/catch in process_batch() (keep ConfigurationError)
   - Add _create_exhausted_record() method to TargetGenerator
   - Add exhaustion handling to _process_by_strategy()
   - Add comprehensive logging at aggregation layer

3. **Phase 3: Batch Mode**
   - Update BatchResultProcessor._stage_6_merge_passthroughs() to use same logic
   - Ensure logging matches online mode
   - Verify exception flow through both entry points

4. **Phase 4: Testing & Documentation**
   - Test online mode with on_exhausted="raise" and "return_last"
   - Test batch mode with both settings
   - Test mixed exhausted/success records
   - Document consolidated behavior

---

## Behavioral Guarantees

### With `on_exhausted="return_last"` (default)
```
Input:  100 records
  ├─ 95 succeed
  ├─ 3 retry exhausted
  └─ 2 fail due to non-retriable errors

Output: 98 records
  ├─ 95 success records (normal data)
  ├─ 3 exhausted records (empty content + _recovery metadata)
  └─ 2 failed records (logged, not in output)

Result: ✅ COMPLETE - All processed records in output with metadata
```

### With `on_exhausted="raise"`
```
Input:  100 records
Processing:
  [Success] [Success] ... [EXHAUSTED detected]

  → Check on_exhausted="raise"
  → Raise AgentActionsException
  → Workflow fails immediately

Output: ❌ NO OUTPUT FILE
Result: ❌ FAILED - Clear error message, no partial output
```

---

## Edge Notes (All Known Edge Cases & Clarifications)

1. **Non-retriable errors vs EXHAUSTED**
   - The current pseudocode breaks out on non-retriable errors and still returns `exhausted=True`.
   - Non-retriable errors must be surfaced as `FAILED` results, not `EXHAUSTED`.
   - `FAILED` records are not included in output (consistent with current `FAILED` handling).

2. **RetryResult.response contract**
   - `retry_result.response` is treated as `(response, executed)` in retry-only branch.
   - In reprompt+retry branch, `retry_result.response` is treated as raw response.
   - Clarify contract: Either always wrap `run_dynamic_agent()` to return `(response, executed)` or always return raw response from retry and let `_execute_llm()` set `executed`.

3. **Exhausted vs failed logging**
   - Avoid double logging of exhaustion: log at aggregation layer only, or ensure upstream logs are `DEBUG`/`INFO`.
   - Log non-retriable `FAILED` errors as error once at aggregation.

4. **Batch global failure semantics**
   - `process_all_batch_results()` currently swallows exceptions and continues.
   - Clarify expectation: Should `on_exhausted="raise"` stop the entire batch job or only fail the specific file?
   - If strict global failure is required, update `process_all_batch_results()` to re-raise.

5. **Output file guarantee**
   - Online path: `on_exhausted="raise"` must guarantee no output file.
   - Batch path: document whether partial outputs can exist if failure occurs late in processing.

6. **Schema defaults for exhausted record**
   - Explicitly define empty field behavior by type:
     - `array`: `[]`
     - `object`: `{}`
     - `boolean`: `False`
     - `number`/`integer`: `0`
     - `string`: `None`
   - Confirm whether null vs missing keys are acceptable.

7. **Recovery metadata presence**
   - `_recovery` should only be attached when retry/reprompt was attempted.
   - Exhausted records must include `_recovery.retry` and `metadata.retry_exhausted=True`.

8. **Mixed outcomes in same batch**
   - Ensure aggregation handles `SUCCESS`, `SKIPPED`, `FILTERED`, `FAILED`, and `EXHAUSTED` deterministically.
   - `FAILED` should stay out of output; `EXHAUSTED` included only if `on_exhausted="return_last"`.

9. **Order stability**
   - If output order matters, ensure `EXHAUSTED` records preserve original item ordering when appended.

10. **Tool action (file granularity)**
    - `_process_file_mode_tool()` must return results compatible with unified aggregation logic (including `EXHAUSTED`).

11. **Context propagation**
    - Ensure `source_guid`, `source_snapshot`, and lineage are preserved for exhausted records.

12. **Config validation**
    - If `retry.on_exhausted` has unexpected values, default to `return_last` and log a warning once.

## Benefits of Unified Approach

1. **Consistent Behavior**: Online and batch modes behave identically
2. **No Silent Failures**: Exhausted records are visible with metadata
3. **Explicit Control**: on_exhausted config fully respected in both modes
4. **Better Observability**: Centralized logging at aggregation layer
5. **Reduced Complexity**: Single exception handling path
6. **Data Integrity**: Output structure matches expectations regardless of retry status
