
import json
from typing import List, Dict, Any

def flatten_code(data):
    """
    Transforms the input data into a list of dictionaries where each item
    from the 'candidate_code_list' list becomes a separate dictionary with
    'fact' and 'quote' keys at the top level.
    
    Parameters:
        data (dict or str): Dictionary containing 'candidate_code_list' list, or JSON string
                            that can be parsed into such a dictionary.
    
    Returns:
        str: JSON string containing the transformed list of dictionaries.
    
    Raises:
        ValueError: If data doesn't contain 'candidate_code_list' key or if JSON is invalid.
        TypeError: If data is not a dict or string.
    """
    # Handle string input (JSON)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON string: {e}")
    
    # Validate input type
    if not isinstance(data, dict):
        raise TypeError("Data must be a dictionary or valid JSON string")
    
    # Check if 'candidate_code_list' exists and is a list
    if 'candidate_code_list' not in data:
        raise ValueError("Input data must contain 'candidate_code_list' key")
    
    if not isinstance(data['candidate_code_list'], list):
        raise ValueError("'candidate_code_list' must be a list")
    
    # Transform the data - flatten fact and quote to top level
    returned_data = []
    for fact_item in data["candidate_code_list"]:
        if isinstance(fact_item, dict):
            # If the fact_item is already a dictionary, use it directly
            returned_data.append(fact_item)
        else:
            # If it's not a dict, assume it's a simple value and create a dict
            returned_data.append({"code": fact_item})
    
    return json.dumps(returned_data)