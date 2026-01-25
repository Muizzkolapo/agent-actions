from typing import Any, Dict
from agent_actions import udf_tool


@udf_tool()
def select_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simple passthrough UDF that returns data as-is.
    Used with guards to filter records based on conditions.
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    # Simply return the content as-is
    # The guard will handle filtering based on the 'filter' field
    return content
