# Cohere Provider Manifest

## Overview

Cohere client adapter for both batch and online calls.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `client.py` | Module | Cohere API client used for prompts and embeddings. A transport failure the SDK lets through (`TRANSPORT_ERRORS`, such as `httpx.ConnectError`) is wrapped as `NetworkError`, so it is retried. | `llm.providers` |
