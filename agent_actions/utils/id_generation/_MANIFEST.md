# ID Generation Manifest

## Overview

Centralized UUID helpers for `target_id`, `node_id`, and deterministic `source_guid`
generation used by processors, UDF registries, and field managers.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `generator.py` | Module | `IDGenerator` methods that emit UUID4 targets, `{action}_{uuid}` node IDs, and deterministic UUID5 source GUIDs. | `field_management`, `lineage` |
| `IDGenerator` | Class | Static helpers `generate_target_id`, `generate_node_id`, and `generate_deterministic_source_guid`. | `field_management`, `lineage` |
