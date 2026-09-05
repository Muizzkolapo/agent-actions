from typing import Any

from agent_actions import udf_tool


@udf_tool
def flatten_pages(data: Any, *args) -> list[dict]:
    """Flatten a page into one record."""
    text = str((data or {}).get("page_content", ""))[:80]
    return [{"summary": text, "exam_density": "low"}]
