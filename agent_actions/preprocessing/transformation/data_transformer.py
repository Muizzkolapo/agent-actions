"""Data transformation utilities for agent actions."""

import copy
from typing import Any, Dict, List, Optional


class DataTransformer:
    """Utility class for data transformations."""

    @staticmethod
    def ensure_list(data):
        """
        Ensure that the input data is returned as a list.

        Args:
            data: Input data that may be a single item, list, or other iterable

        Returns:
            list: The data as a list
        """
        if data is None:
            return []
        elif isinstance(data, list):
            return data
        elif isinstance(data, (str, dict, int, float, bool)):
            return [data]
        else:
            # Handle other iterables (tuples, sets, etc.)
            try:
                return list(data)
            except (TypeError, ValueError):
                # If conversion fails, wrap in list
                return [data]

    @staticmethod
    def remove_schema_objects(data: Dict[str, Any], keys_to_remove: List[str]) -> Dict[str, Any]:
        """
        Removes specified keys from a dictionary without side effects.

        Args:
            data: The dictionary from which keys should be removed
            keys_to_remove: A list of keys to remove

        Returns:
            New dictionary with specified keys removed
        """
        if not isinstance(data, dict):
            return data
        if not keys_to_remove:
            return data

        # Create a new dictionary excluding the keys to remove
        return {k: v for k, v in data.items() if k not in keys_to_remove}

    @staticmethod
    def update_schema_objects(
        data_old: Dict[str, Any],
        data_new: Dict[str, Any],
        keys_to_update: List[str]
    ) -> Dict[str, Any]:
        """
        Updates data based on structure comparison without side effects.

        - If the value types match for a given key, replace data_new value with data_old value.
        - If the value types differ, append the data_old key/value into data_new.

        Args:
            data_old: Original data dictionary
            data_new: Dictionary to be updated
            keys_to_update: Keys to be considered for updating

        Returns:
            New dictionary with updates applied
        """
        # Create a deep copy to ensure no side effects
        result = copy.deepcopy(data_new)

        for key in keys_to_update:
            if key in data_old:
                old_value = data_old[key]
                new_value = result.get(key)

                if new_value is not None:
                    if isinstance(old_value, type(new_value)):
                        result[key] = copy.deepcopy(old_value)
                    else:
                        # Create list with both values
                        result[key] = [new_value, copy.deepcopy(old_value)]
                else:
                    result[key] = copy.deepcopy(old_value)

        return result

    @staticmethod
    def transform_structure(data: List[Dict]) -> List[Dict]:
        """
        Transforms nested dictionary structure to flat list without side effects.

        Args:
            data: List of dictionaries with nested contents

        Returns:
            Transformed flat list of dictionaries
        """
        result = []

        for data_item in data:
            if isinstance(data_item, dict):
                for source_guid, contents in data_item.items():
                    if isinstance(contents, list):
                        for content in contents:
                            result.append({
                                "source_guid": source_guid,
                                "content": content
                            })
                    else:
                        result.append({
                            "source_guid": source_guid,
                            "content": contents
                        })

        return result

    @staticmethod
    def get_content_by_source_guid(
        data: List[Dict[str, Any]],
        source_guid: str
    ) -> Optional[Any]:
        """
        Retrieve content by source_guid without side effects.

        Args:
            data: List of dictionaries with 'source_guid' field
            source_guid: The source_guid to search for

        Returns:
            The content associated with the source_guid, or None if not found
        """
        for item in data:
            if isinstance(item, dict):
                # Check if source_guid matches
                if item.get('source_guid') == source_guid:
                    return item
        return None