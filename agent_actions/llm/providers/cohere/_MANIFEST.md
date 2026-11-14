# Cohere Provider Manifest

## Overview

Cohere client adapter for both batch and online calls.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `client.py` | Module | Cohere API client used for prompts and embeddings. A transport failure the SDK lets through (`TRANSPORT_ERRORS`, such as `httpx.ConnectError`) is wrapped as `NetworkError`, so it is retried. `VENDOR_PARAMS` takes every keyword of `ClientV2.chat` but `request_options`. A response with no content names its `finish_reason`; `MAX_TOKENS` is a `ResponseTruncatedError`. | `llm.providers` |
