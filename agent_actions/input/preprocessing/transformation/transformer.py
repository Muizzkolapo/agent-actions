"""Data transformation utilities for agent actions."""

import copy
from typing import Any


class DataTransformer:
    """Utility class for data transformations."""

    @staticmethod
    def ensure_list(data: Any) -> list[Any]:
        """Ensure that the input data is returned as a list."""
        if data is None:
            result: list[Any] = []
        elif isinstance(data, list):
            result = data
        elif isinstance(data, str | dict | int | float | bool):
            result = [data]
        else:
            try:
                result = list(data)
            except (TypeError, ValueError):
                result = [data]

        return result

    @staticmethod
    def remove_schema_objects(data: dict[str, Any], keys_to_remove: list[str]) -> dict[str, Any]:
        """Return a new dictionary with specified keys removed."""
        if not isinstance(data, dict):
            return data  # type: ignore[unreachable]
        if not keys_to_remove:
            return data

        return {k: v for k, v in data.items() if k not in keys_to_remove}

    @staticmethod
    def update_schema_objects(
        data_old: dict[str, Any], data_new: dict[str, Any], keys_to_update: list[str]
    ) -> dict[str, Any]:
        """Merge keys from data_old into data_new: replace if same type, combine if types differ."""
        result = copy.deepcopy(data_new)

        for key in keys_to_update:
            if key in data_old:
                old_value = data_old[key]
                new_value = result.get(key)

                if new_value is not None:
                    if isinstance(old_value, type(new_value)):
                        result[key] = copy.deepcopy(old_value)
                    else:
                        result[key] = [new_value, copy.deepcopy(old_value)]
                else:
                    result[key] = copy.deepcopy(old_value)

        return result

    @staticmethod
    def transform_structure(data: list[dict]) -> list[dict]:
        """Flatten nested {source_guid: contents} structure to list of dicts."""
        result = []

        for data_item in data:
            if isinstance(data_item, dict):
                for source_guid, contents in data_item.items():
                    if isinstance(contents, list):
                        for content in contents:
                            result.append({"source_guid": source_guid, "content": content})
                    else:
                        result.append({"source_guid": source_guid, "content": contents})

        return result

    @staticmethod
    def get_content_by_source_guid(data: list[dict[str, Any]], source_guid: str) -> Any | None:
        """Find and return the item matching the given source_guid, or None."""
        for item in data:
            if isinstance(item, dict):
                if item.get("source_guid") == source_guid:
                    return item
        return None
