# Ollama Provider Manifest

## Overview

Local Ollama adapter offering batch/online clients plus failure injection helpers.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client interfacing with Ollama daemon. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Ollama client for streaming responses. A refused connection (which the ollama SDK re-raises as a builtin `ConnectionError`) or any other transport failure (`TRANSPORT_ERRORS`) is wrapped as `NetworkError`, so it is retried. | `llm.realtime`, `llm.providers` |
| `failure_injection.py` | Module | Simulates failures/latency for Ollama tests. | `tests`, `llm.providers` |
