# Batch Processing Manifest

## Overview

Models that prepare batch inputs, reconcile outputs, and process results
before persisted results are written.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `preparator.py` | Module | Prepares batch workloads (chunking, formatting, batching). A record whose prompt cannot be prepared is marked failed on its context-map entry, which keeps the error (`_batch_prep_error`, 500 characters) whether or not its state could move to failed; so is one refused for having no source_guid, which is never submitted. The preflight sample passes over a refused record as it passes over a guard skip, so one at the head of the input does not stop the action. | `preprocessing`, `input` |
| `reconciler.py` | Module | Reconciles batch outputs with context; uses string-normalized custom_id for JSON compatibility. A record the context map holds without a `source_guid` has none: its custom_id, a target_id, is never handed out as one, so enrichment refuses it, as it refuses whatever reaches it without one (a guard skip, or a record in a batch an earlier release sent). Nor is an id the map does not hold, such as a parser placeholder: it names no record. `resendable_ids` leaves a record with no `source_guid` out of what a retry sends again: preparation would refuse it, so it is collected unanswered and refused at enrichment. | `formatting`, `output` |
| `batch_result_strategy.py` | Module | Batch result processing strategy; converts raw BatchResult objects into enriched ProcessingResult records, and every context entry no result answers into the result preparation found it to be (none at all collects a run that sent nothing). An empty answer goes by the action's `on_empty`, as online: `warn` a failed record, `skip` a tombstone, `error` a failed record, on which the service raises `EmptyOutputError` once the file is written. A preparation failure's result carries the error preparation kept, which its disposition records as online's does; its row says `prep_failed`, and a context map saved before the error was kept gives `prep_failed` too. One with no source_guid carries no row: the collector builds it from the record, as it builds online's, where a tombstone without the identity would be refused again at enrichment. | `processing`, `output` |
