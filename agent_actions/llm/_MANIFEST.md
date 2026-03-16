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
