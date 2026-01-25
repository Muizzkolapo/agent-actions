import ast
import json
import re
from typing import Any, Dict, List
from agent_actions import udf_tool


def _try_parse_options_string(options_str: str) -> List[str]:
    # Try JSON first
    try:
        parsed = json.loads(options_str)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try to extract a JSON array inside the string
    match = re.search(r"\[(.*)\]", options_str, re.DOTALL)
    if match:
        try:
            parsed = json.loads("[" + match.group(1) + "]")
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Try ast literal eval as fallback
    try:
        cleaned = options_str.replace('\\"', '"').replace("\\'", "'")
        parsed = ast.literal_eval(cleaned)
        if isinstance(parsed, list):
            return parsed
    except (ValueError, SyntaxError):
        pass

    # Last resort: extract quoted strings
    matches = re.findall(r'"([^"]+)"', options_str)
    if matches:
        return [m.strip() for m in matches if m.strip()]

    return []


@udf_tool()
def fix_options_formatting(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure options is a list. If it's a JSON-like string, parse it.
    Returns the original record with options fixed when possible.
    """
    if not isinstance(data, dict):
        return data

    options = data.get("options")
    if isinstance(options, list):
        return data

    if isinstance(options, str):
        parsed = _try_parse_options_string(options)
        if parsed:
            updated = data.copy()
            updated["options"] = parsed
            return updated

    return data
