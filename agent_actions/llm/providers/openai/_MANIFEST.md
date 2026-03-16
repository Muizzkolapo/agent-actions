# OpenAI Provider Manifest

## Overview

Adapter for OpenAI APIs that differentiates tool/batch/online clients across the
project.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client for uploading and monitoring OpenAI jobs. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online OpenAI client supporting tool calls and streaming. | `llm.realtime`, `llm.providers` |
