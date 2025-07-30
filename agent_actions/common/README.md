# Common

This directory contains shared utilities and interfaces used throughout the agent-actions framework.

## Structure

- `interfaces/` - Common interface definitions for all components
- `utils/` - Shared utility functions and helper classes
- `transformers/` - Data transformation utilities

## Purpose

Common modules provide:
- Standardized interfaces for consistency across components
- Shared utility functions to avoid code duplication
- Data transformation and processing utilities
- Common patterns and mixins

## Key Components

- `interfaces.py` - Core interfaces (ILoader, IProcessor, IGenerator, etc.)
- `base_async_processor.py` - Base class for async-capable processors
- Data transformers for common data manipulation tasks