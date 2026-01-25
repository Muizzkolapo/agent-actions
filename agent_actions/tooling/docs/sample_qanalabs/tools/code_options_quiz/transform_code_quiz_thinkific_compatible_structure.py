from typing import Any, Dict, List
from agent_actions import udf_tool


@udf_tool()
def transform_code_quiz_thinkific_compatible_structure(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Transform quiz data into Thinkific-compatible structure.

    Args:
        data: Quiz data with question, options, answer, explanation

    Returns:
        List with transformed quiz record
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Forward all fields as-is for now
    # This is a passthrough that ensures compatibility
    result = content.copy()

    return [result]
