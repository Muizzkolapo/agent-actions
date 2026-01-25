import json
from typing import Any, Dict, List, Set
from agent_actions import udf_tool



@udf_tool()
def apply_edited_distractors(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    print(data)
    return [data]
