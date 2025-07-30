# Processors

This directory contains processing logic for the agent-actions framework.

## Structure

- `content/` - Content processing logic (prompt processing, response transformation)
- `pipeline/` - Pipeline-based processing framework
- `async/` - Asynchronous processing utilities

## Purpose

Processors are responsible for:
- Processing and transforming data between pipeline stages
- Content-specific processing (prompts, responses, etc.)
- Pipeline orchestration and stage management
- Asynchronous processing coordination

## Key Interfaces

All processors implement the `IProcessor` or `IContentProcessor` interfaces from `common.interfaces`.

## Legacy Note

Some legacy processor directories remain for backward compatibility but will be deprecated in future versions.