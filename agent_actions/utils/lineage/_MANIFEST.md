# Lineage Manifest

## Overview

Captures ancestral lineage information for processed items, including ancestry
chain propagation (`parent_target_id`, `root_target_id`) and multi-source
lineage_sources tracking.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `builder.py` | Module | `LineageBuilder` helpers that validate node IDs, append lineage, propagate ancestry chain IDs, and merge multi-source traces. | `preprocessing`, `lineage` |
| `LineageBuilder` | Class | Static helpers like `build_lineage`, `add_lineage_tracking`, `add_lineage_tracking_from_sources`, and `add_unified_lineage`. | `preprocessing`, `logging` |
