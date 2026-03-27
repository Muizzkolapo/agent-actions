# AGAC Provider Manifest

## Overview

Claude-branded provider adapter (AGAC) with non-blocking clients and test helpers.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client that uploads jobs to Claude/AGAC. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online client for Claude Code/AGAC interactions. | `llm.realtime`, `llm.providers` |
| `fake_data.py` | Module | Test helpers that simulate Claude responses. | `tests`, `llm.providers` |
