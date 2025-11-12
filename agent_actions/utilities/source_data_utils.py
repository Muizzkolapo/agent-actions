"""Utilities for source data manipulation.

This module provides utility functions for working with source data,
including deduplication and format validation.
"""

from typing import List, Dict, Any


def deduplicate_by_source_guid(
    existing: List[Dict[str, Any]],
    new: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Deduplicate items by source_guid field.

    Compares new items against existing items and returns only those
    that don't already exist based on their source_guid field.

    Args:
        existing: List of existing items with source_guid field
        new: List of new items to deduplicate against existing

    Returns:
        List of items from 'new' that don't exist in 'existing'

    Example:
        >>> existing = [{'source_guid': 'a', 'data': 1}]
        >>> new = [{'source_guid': 'a', 'data': 2}, {'source_guid': 'b', 'data': 3}]
        >>> deduplicate_by_source_guid(existing, new)
        [{'source_guid': 'b', 'data': 3}]
    """
    # Extract existing GUIDs for fast lookup
    existing_guids = {
        item.get('source_guid')
        for item in existing
        if isinstance(item, dict) and item.get('source_guid')
    }

    # Filter out items that already exist
    return [
        item
        for item in new
        if isinstance(item, dict)
        and item.get('source_guid')
        and item.get('source_guid') not in existing_guids
    ]
