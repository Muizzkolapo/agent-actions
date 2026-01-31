# Agent Context

## Project Structure
This project uses the **Agent Manifest Protocol (AMP)** for navigation.
**[> Open Codebase Map (agent_actions/_MANIFEST.md)](agent_actions/_MANIFEST.md)**

## Overview
Agent Actions is a framework for building and orchestrating AI agents.

## Development Guidelines

### Setup
- **Install:** `uv sync`
- **Activate:** `source .venv/bin/activate`

### Testing
- **Run Tests:** `pytest`
- **Lint:** `ruff check .`
- **Format:** `ruff format .`

### Architecture
- **Core Logic:** Located in `agent_actions/`.
- **CLI:** Entry points in `agent_actions/cli`.
- **Docs:** Generated from `agent_actions/docs`.

### Manifest Maintenance
- **Always update `_MANIFEST.md` files** when making code changes that add, remove, or modify modules, classes, or functions.
- Each directory has its own `_MANIFEST.md` that documents its contents.
- Keep manifests in sync with the actual code to maintain accurate navigation.

### Navigation Strategy
1.  **Start Here:** Use this file for high-level context.
2.  **Explore:** Follow the `_MANIFEST.md` link above to traverse the codebase structure.
3.  **Inspect:** Read individual `_MANIFEST.md` files in subdirectories to find specific symbols and dependencies ("Signals").
4.  **Read Code:** Only read source files when you have pinpointed the exact location.
