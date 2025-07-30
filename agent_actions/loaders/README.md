# Loaders

This directory contains all data loading functionality for the agent-actions framework.

## Structure

- `data_loaders/` - Format-specific data loaders (JSON, XML, CSV, etc.)
- `file_loaders/` - File-specific loading operations
- `config_loaders/` - Configuration loading utilities

## Purpose

Loaders are responsible for:
- Reading data from various file formats
- Parsing and validating input data
- Converting raw data into standardized formats
- Handling different data sources (files, databases, APIs)

## Key Interfaces

All loaders implement the `IDataLoader` or `ISourceDataLoader` interfaces from `common.interfaces`.