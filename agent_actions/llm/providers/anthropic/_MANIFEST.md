# Anthropic Provider Manifest

## Overview

Anthropic-specific batch and online clients plus the thin adapter glue.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client implementing Anthropic's API. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Anthropic client for streaming responses. | `llm.realtime`, `llm.providers` |
