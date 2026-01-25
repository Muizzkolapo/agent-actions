from typing import Any, Dict, List
from agent_actions import udf_tool


@udf_tool()
def flatten_code(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flatten candidate_code_list into individual records.

    Args:
        data: Dictionary containing candidate_code_list

    Returns:
        List of flattened code records with shared fields
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Extract the code list
    code_list = content.get('candidate_code_list', [])
    if not code_list:
        return []

    # Extract shared fields (everything except candidate_code_list)
    shared_fields = {k: v for k, v in content.items() if k != 'candidate_code_list'}

    # Flatten: merge shared fields with each code item
    flattened = []
    for code_item in code_list:
        if isinstance(code_item, dict):
            record = {**shared_fields, **code_item}
            flattened.append(record)

    return flattened
