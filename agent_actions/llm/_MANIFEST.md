# LLM Manifest

## Overview

LLM integrations provide both batch and online execution paths, vendor profile
configuration, and a growing set of provider adapters (OpenAI, Anthropic, Claude,
Cohere, etc.).

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [batch](batch/_MANIFEST.md) | Batch execution helpers, CLI entrypoints, and services for running workflows as jobs. |
| [config](config/_MANIFEST.md) | Shared vendor configuration utilities. |
| [providers](providers/_MANIFEST.md) | Provider-specific clients, failure injection, usage tracking, and tooling. |
| [realtime](realtime/_MANIFEST.md) | Online runner utilities, context handlers, and invocation services. |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `AgentManager.get_agent_paths()` | `agent_actions.yml` | Reads | — |
| `AgentManager.get_agent_paths()` | `agent_config/{workflow}.yml` | Reads | — |
| `ClientInvocationService.invoke_client()` | `.env` | Reads | `actions[].model_vendor` |
| `ToolClient.invoke()` | `tools/{workflow}/*.py` | Reads | `actions[].impl` |
| `BaseVendorConfig` | `.env` | Reads | `api_key_env_name` |
| `create_dynamic_agent()` | `schema/{workflow}/{action}.yml` | Reads | `actions[].schema` |
| `OutputHandler.save_main_output()` | `agent_io/target/{action}/` | Writes | — |
| `BatchSubmissionService.submit()` | `agent_io/staging/` | Reads | — |
| `BatchRetrievalService.retrieve()` | `agent_io/target/{action}/` | Writes | — |
| `batch_cli` | `agent_actions.yml` | Reads | — |

**Internal only**: `VendorType`, `ResponseFormat`, `VendorRegistry`, `VendorConfig`, `BatchJobEntry`, `SubmissionResult`, `BatchContextManager`, `BatchRegistryManager`, `BatchContextMetadata`, `BatchTaskPreparator`, `BatchClientResolver`, `ContextService`, `PromptService`, `CLIENT_REGISTRY`, `SINGLE_RESPONSE_CLIENTS` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `workflow` | inbound | Workflow executor invokes batch and online runners |
| `cli` | inbound | CLI commands dispatch to batch_cli and realtime handlers |
| `prompt` | outbound | Uses MessageBuilder and PromptPreparationService for prompt assembly |
| `processing` | outbound | Uses RecordProcessor and EnrichmentPipeline for result processing |
| `config` | outbound | Reads vendor profiles and project paths from config utilities |
| `output` | outbound | Uses ResponseSchemaCompiler and FileWriter for output handling |
| `input` | outbound | Uses loaders and preprocessing for batch data preparation |
| `storage` | outbound | Persists batch registry and result dispositions via StorageBackend |
