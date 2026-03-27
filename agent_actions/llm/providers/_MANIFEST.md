# LLM Providers Manifest

## Overview

Provider adapters expose batch/online clients, failure injection helpers, and
shared utilities (mixins, usage tracking) for each supported LLM vendor.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_base.py` | Module | Base helpers shared by batch clients (request shaping, telemetry). | `llm.batch` |
| `batch_client_factory.py` | Module | Factory that returns a provider-specific batch client implementation. | `llm.batch`, `llm.providers` |
| `client_base.py` | Module | Abstract base client that defines the interface for streaming/call semantics. | `llm.providers`, `llm.realtime` |
| `error_wrapper.py` | Module | Unified vendor error wrapping: maps SDK exceptions to RateLimitError/NetworkError/VendorAPIError. | `errors`, `llm.providers` |
| `failure_injection.py` | Module | Utility to simulate latency/failure scenarios across providers. | `logging`, `llm.providers` |
| `generation_params.py` | Module | Shared helper (`extract_generation_params`) for extracting temperature/max_tokens/top_p/stop from agent config with vendor-specific key mapping. | `llm.providers` |
| `mixins.py` | Module | Shared mixins for access token handling, logging, context propagation. | `llm.providers` |
| `usage_tracker.py` | Module | Central usage tracking and quota summary used by providers. | `logging`, `llm.providers` |
| `agac/__init__.py` | Module | `agac` (Claude-branded) provider helpers (callbacks, config). | `llm.providers` |
| `anthropic/__init__.py` | Module | Anthropic-specific client wrappers and guardrails. | `llm.providers`, `anthropic` |
| `cohere/__init__.py` | Module | Cohere provider adapter for embeddings/inference. | `llm.providers`, `cohere` |
| `gemini/__init__.py` | Module | Gemini provider wiring (Google Gemini). | `llm.providers`, `google` |
| `groq/__init__.py` | Module | Groq provider binding for Groq Cloud inference. | `llm.providers`, `groq` |
| `mistral/__init__.py` | Module | Mistral provider integration. | `llm.providers`, `mistral` |
| `ollama/__init__.py` | Module | Ollama provider connector for local inference. | `llm.providers`, `ollama` |
| `openai/__init__.py` | Module | OpenAI provider adapter with tool/window shaping. | `llm.providers`, `openai` |
| `tools/__init__.py` | Module | Tool discovery/registration for OpenAI function calling formats. | `llm.providers`, `tools` |
| `hitl/__init__.py` | Module | Human-in-the-loop provider for synchronous approval/rejection workflows. | `llm.providers`, `hitl` |
