"""Pure function implementations of data transformations."""

from typing import Any, Dict, List, Optional, Union, Tuple
import copy


class PureDataTransformer:
    """
    Collection of pure transformation functions.
    
    All functions are side-effect free and return new data structures
    without modifying the input.
    """
    
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
    def remove_schema_objects(
        data: Dict[str, Any],
        keys_to_remove: List[str]
    ) -> Dict[str, Any]:
        """
        Removes specified keys from a dictionary without side effects.
        
        Args:
            data: The dictionary from which keys should be removed
            keys_to_remove: A list of keys to remove
            
        Returns:
            New dictionary with specified keys removed
        """
        # Create a new dictionary excluding the keys to remove
        return {k: v for k, v in data.items() if k not in keys_to_remove}
    
    @staticmethod
    def extract_objects(input_data: Union[Dict, List]) -> List[Any]:
        """
        Extracts lists from nested structures without side effects.
        
        Args:
            input_data: Dictionary or list containing nested data
            
        Returns:
            Extracted list of objects
        """
        if isinstance(input_data, list):
            # For list input, check first item for nested lists
            if input_data and isinstance(input_data[0], dict):
                for value in input_data[0].values():
                    if isinstance(value, list):
                        return value
            return input_data
        elif isinstance(input_data, dict):
            # For dict input, find first list value
            for value in input_data.values():
                if isinstance(value, list):
                    return value
        
        return []
    
    @staticmethod
    def flatten_to_list_of_dicts(nested_lists: List[List[Dict]]) -> List[Dict]:
        """
        Flattens nested lists into a single list without side effects.
        
        Args:
            nested_lists: A nested list where each inner list contains dictionaries
            
        Returns:
            A flat list containing all dictionaries
        """
        result = []
        for sublist in nested_lists:
            if isinstance(sublist, list):
                result.extend(sublist)
            else:
                # Handle case where item is not a list
                result.append(sublist)
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
                        # Handle non-list content
                        result.append({
                            "source_guid": source_guid,
                            "content": contents
                        })
        
        return result
    
    @staticmethod
    def ensure_list(obj: Any) -> List[Any]:
        """
        Ensures the input is a list without modifying the original.
        
        Args:
            obj: The object to ensure as a list
            
        Returns:
            The object wrapped in a list if it wasn't already
        """
        if isinstance(obj, list):
            return obj
        return [obj]
    
    @staticmethod
    def get_content_by_source_guid(
        data: List[Dict[str, Any]],
        source_guid: str
    ) -> Optional[Any]:
        """
        Retrieve content by source_guid without side effects.
        
        Args:
            data: List containing dictionaries with GUIDs as keys
            source_guid: The source_guid to search for
            
        Returns:
            The content associated with the source_guid, or None if not found
        """
        for item in data:
            if isinstance(item, dict) and source_guid in item:
                return item[source_guid]
        return None
    
    @staticmethod
    def merge_with_type_checking(
        base_data: Dict[str, Any],
        update_data: Dict[str, Any],
        type_strict: bool = True
    ) -> Dict[str, Any]:
        """
        Merge dictionaries with optional type checking.
        
        Args:
            base_data: Base dictionary
            update_data: Dictionary with updates
            type_strict: If True, only merge values of same type
            
        Returns:
            New merged dictionary
        """
        result = copy.deepcopy(base_data)
        
        for key, value in update_data.items():
            if key in result and type_strict:
                if isinstance(value, type(result[key])):
                    result[key] = copy.deepcopy(value)
            else:
                result[key] = copy.deepcopy(value)
        
        return result
    
    @staticmethod
    def filter_by_condition(
        data: List[Dict[str, Any]],
        condition: callable
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Filter data based on condition, returning both matching and non-matching.
        
        Args:
            data: List of dictionaries to filter
            condition: Function that returns True for items to keep
            
        Returns:
            Tuple of (matching_items, non_matching_items)
        """
        matching = []
        non_matching = []
        
        for item in data:
            if condition(item):
                matching.append(item)
            else:
                non_matching.append(item)
        
        return matching, non_matching
    
    @staticmethod
    def group_by_field(
        data: List[Dict[str, Any]],
        field: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group list of dictionaries by a field value.
        
        Args:
            data: List of dictionaries
            field: Field name to group by
            
        Returns:
            Dictionary with field values as keys and lists of items as values
        """
        grouped = {}
        
        for item in data:
            if isinstance(item, dict) and field in item:
                key = item[field]
                if key not in grouped:
                    grouped[key] = []
                grouped[key].append(item)
        
        return grouped
    
    @staticmethod
    def map_values(
        data: Dict[str, Any],
        mapper: callable,
        keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Apply a mapping function to dictionary values.
        
        Args:
            data: Dictionary to transform
            mapper: Function to apply to values
            keys: Optional list of keys to transform (None = all keys)
            
        Returns:
            New dictionary with transformed values
        """
        result = {}
        
        for key, value in data.items():
            if keys is None or key in keys:
                result[key] = mapper(value)
            else:
                result[key] = value
        
        return result