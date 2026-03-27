# Groq Provider Manifest

## Overview

Groq Cloud integration with batch and streaming helpers.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client for scheduling Groq jobs. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Groq client for low-latency inference. | `llm.realtime`, `llm.providers` |
