# Filtering Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `filter_service.py` | Module | Centralized filtering logic for guard condition and conditional clause evaluation. | `preprocessing`, `utilities` |
| `FilterStatus` | Class | Result of filtering a single item. | - |
| `FilterService` | Class | Centralized filtering service for WHERE clause and conditional clause evaluation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_single_item` | Method | Filter a single item using guard condition or conditional clause. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `apply_guard_filtering` | Method | Apply guard filtering to a list of data items (realtime mode). | - |
| `get_filter_service` | Function | Get the global FilterService instance. | - |
| `guard_filter.py` | Module | Guard filter service. | `utilities` |
| `FilterResult` | Class | Result of filtering operation. | - |
| `FilterMetrics` | Class | Metrics for filter operations. | - |
| `FilterItemRequest` | Class | Request parameters for filtering a single item. | - |
| `FilterBatchRequest` | Class | Request parameters for filtering a batch of items. | - |
| `GuardFilter` | Class | Guard filter with security, performance, and reliability improvements. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_item` | Method | Filter a single data item using a guard condition. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_batch` | Method | Filter a batch of data items using a guard condition. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate_safe_skip_condition` | Method | Safely evaluate a skip condition without using eval(). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_cache_info` | Method | Get cache statistics. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_cache` | Method | Clear all caches. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `shutdown` | Method | Shutdown the filter service. | - |
| `get_global_guard_filter` | Function | Get the global guard filter instance. | - |
| `evaluate_safe_skip_condition` | Function | Safely evaluate a skip condition. | - |
| `guard_handler.py` | Module | Unified guard condition handling across batch and online modes. | `preprocessing`, `utilities` |
| `FilterBehavior` | Class | Filter behavior options. | - |
| `GuardConfig` | Class | Validated guard configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_dict` | Method | Create GuardConfig from dict, returns None if invalid. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dict for FilterService compatibility. | - |
| `GuardFilteringContext` | Class | Unified filtering context tracking for both modes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `track` | Method | Track filtering decision for an item. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_summary` | Method | Get summary statistics. | - |
| `GuardHandler` | Class | Unified guard filtering coordinator for batch and online modes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_config` | Method | Validate and normalize guard config. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_evaluate_at_item_level` | Method | Check if guard applies at item level. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_single_item` | Method | Filter single item (batch mode pattern). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_single_item_with_context` | Method | Filter single item WITH full upstream context access. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_items_batch_mode` | Method | Filter items for batch mode with full context tracking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_items_online_mode` | Method | Filter items for online mode (bulk pre-filtering). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_passthrough_item` | Method | Create passthrough item for skipped entries. | - |
| `get_guard_handler` | Function | Get global GuardHandler instance (convenience function). | - |
