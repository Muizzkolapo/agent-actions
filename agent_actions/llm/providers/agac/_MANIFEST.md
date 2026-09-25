# AGAC Provider Manifest

## Overview

Claude-branded provider adapter (AGAC) with non-blocking clients and test helpers.

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `AgacBatchClient._write_state()` | `.agac/batch_state/{batch_id}.json` | Writes | — |
| `AgacBatchClient._load_state()` | `.agac/batch_state/{batch_id}.json` | Reads | — |
| `AgacBatchClient.release_batch()` | `.agac/batch_state/{batch_id}.json` | Deletes | — |
| `AgacBatchClient.discard_partial_writes()` | `.agac/batch_state/*.tmp` | Deletes | — |
| `AgacBatchClient.reset()` | `.agac/batch_state/` | Deletes | — |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Offline batch client for testing batch without a vendor. Records a submitted batch under `.agac/batch_state/` in the project so the run that collects it — a separate process, because submitting pauses and asks to be run again — can find it. Answers each task from the schema and prompt that task carries. The record outlives the read: collecting hands bytes to a caller that has yet to write and evaluate them, and a re-run must find the same batch. It dies with the registry entry that names it. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online client for Claude Code/AGAC interactions. | `llm.realtime`, `llm.providers` |
| `fake_data.py` | Module | Test helpers that simulate Claude responses. | `tests`, `llm.providers` |
