# Agent Manifest Protocol: Next Steps

This document outlines the roadmap for the Agent Manifest Protocol (AMP) implementation.

## Immediate Actions

### 1. Automation via Pre-Commit
To ensure `_MANIFEST.md` files never drift from the actual codebase, the generation script should be added to the `.pre-commit-config.yaml`.

**Proposed Config:**
```yaml
  - repo: local
    hooks:
      - id: generate-manifest
        name: Generate Agent Manifests
        entry: python scripts/generate_manifest.py
        language: system
        pass_filenames: false
        always_run: true
```

## Future Roadmap

### 1. Polyglot Support via Tree-sitter
As outlined in the [AMP Specification](specs/agent_manifest_protocol.md), the current Python `ast` implementation should be replaced or augmented with **Tree-sitter**.

**Goal:** Support manifest generation for:
*   TypeScript/JavaScript (Frontend/Node)
*   Go (High-performance services)
*   Rust (Core systems)

**Implementation Plan:**
1.  Install `tree-sitter` python bindings.
2.  Create language-specific query modules in `scripts/manifest_parsers/`.
3.  Update `generate_manifest.py` to detect file extensions and select the correct parser.

### 2. VS Code Extension
Create a lightweight VS Code extension that renders `_MANIFEST.md` files as a side-panel tree view, allowing human developers to navigate the "Agent View" of the codebase.
