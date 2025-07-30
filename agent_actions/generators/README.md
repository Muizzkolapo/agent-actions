# Generators

This directory contains all generation functionality for the agent-actions framework.

## Structure

- `content/` - Content generation logic (data generators, content generators)
- `output/` - Output generation and formatting
- `templates/` - Template-based generation utilities

## Purpose

Generators are responsible for:
- Creating new content using AI agents
- Generating structured output from processed data
- Managing output formatting and file creation
- Template-based content generation

## Key Interfaces

All generators implement the `IGenerator` or `IDataGenerator` interfaces from `common.interfaces`.