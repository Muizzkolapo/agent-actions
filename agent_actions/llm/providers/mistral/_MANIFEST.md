# Mistral Provider Manifest

## Overview

Mistral-specific clients for both batch and realtime execution modes.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch runner targeting the Mistral API. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Realtime client that streams Mistral responses. | `llm.realtime`, `llm.providers` |
