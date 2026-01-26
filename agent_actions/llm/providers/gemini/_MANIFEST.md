# Gemini Provider Manifest

## Overview

Google Gemini adapter with batch/realtime clients.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch Gemini client implementation. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Realtime Gemini client wrapper with prompt shaping. | `llm.realtime`, `llm.providers` |
