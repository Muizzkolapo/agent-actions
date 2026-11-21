# Cohere Provider Manifest

## Overview

Cohere client adapter for both batch and online calls.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `client.py` | Module | Cohere API client used for prompts and embeddings. A transport failure the SDK lets through (`TRANSPORT_ERRORS`, such as `httpx.ConnectError`) is wrapped as `NetworkError`, so it is retried. `VENDOR_PARAMS` takes every keyword of `ClientV2.chat` but `request_options`. JSON mode sends the schema as `response_format.json_schema`, the field `JsonResponseFormatV2` reads. The answer is the reply's first text item (`_answer_text`), so a thinking item before it is skipped. A response with no text item names its `finish_reason`; `MAX_TOKENS` is a `ResponseTruncatedError`. A JSON answer cut off at `MAX_TOKENS` is a parse error naming it (`cut_off_parse_error`), never repaired into a partial object. | `llm.providers` |
