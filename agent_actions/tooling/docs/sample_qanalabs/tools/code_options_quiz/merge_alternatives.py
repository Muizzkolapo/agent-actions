from typing import Any, Dict, List
from agent_actions import udf_tool


@udf_tool()
def merge_alternatives(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Merge versioned code alternatives into a single record.

    After loop with pattern: merge, this receives NESTED data:
    {
      "generate_code_alternatives_1": { "alternative_code_1": "...", "issue_type_1": "..." },
      "generate_code_alternatives_2": { "alternative_code_2": "...", "issue_type_2": "..." },
      "generate_code_alternatives_3": { "alternative_code_3": "...", "issue_type_3": "..." }
    }

    Args:
        data: Dictionary with nested alternatives from loop

    Returns:
        List with single merged record containing all alternatives
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Start with base fields (non-versioned)
    result = {}

    # Extract fields from nested structure
    for i in range(1, 4):  # alternatives 1, 2, 3
        version_key = f'generate_code_alternatives_{i}'

        if version_key in content and isinstance(content[version_key], dict):
            version_data = content[version_key]

            # Merge all fields from this version
            for key, value in version_data.items():
                result[key] = value

    # Forward any non-versioned fields
    for key, value in content.items():
        if not key.startswith('generate_code_alternatives_'):
            result[key] = value

    return [result]
