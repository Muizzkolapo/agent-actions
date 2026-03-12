"""Resolve tools_path from agent configuration (legacy, simple, and OpenAI formats)."""

import logging
from typing import Dict, Any, Optional

import yaml

logger = logging.getLogger(__name__)


def resolve_tools_path(agent_config: Dict[str, Any]) -> Optional[str]:
    """Resolve tools path from agent config, or None if not found.

    Supports legacy ``tool_path`` (str/list), simple ``tools.path``,
    and OpenAI function-calling ``tools[].function.file`` formats.
    """
    tool_path = agent_config.get("tool_path")
    if tool_path:
        if isinstance(tool_path, list) and len(tool_path) > 0:
            logger.debug("Resolved tools_path from tool_path list: %s", tool_path[0])
            return tool_path[0]
        if isinstance(tool_path, str):
            logger.debug("Resolved tools_path from tool_path string: %s", tool_path)
            return tool_path

    tools = agent_config.get("tools", [])

    if isinstance(tools, dict) and "path" in tools:
        path = tools.get("path")
        logger.debug("Resolved tools_path from tools.path: %s", path)
        return path

    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and tool.get("type") == "function":
                function_def = tool.get("function", {})
                if "file" in function_def:
                    try:
                        tool_file_path = function_def["file"]
                        with open(tool_file_path, "r", encoding="utf-8") as f:
                            tool_config = yaml.safe_load(f)
                            if tool_config and "module_path" in tool_config:
                                module_path = tool_config["module_path"]
                                logger.debug(
                                    "Resolved tools_path from OpenAI tool config: %s", module_path
                                )
                                return module_path
                    except (
                        yaml.YAMLError,
                        FileNotFoundError,
                        PermissionError,
                        IsADirectoryError,
                    ) as e:
                        logger.warning(
                            "Failed to load tool config from %s: %s", function_def.get("file"), e
                        )

    logger.debug("No tools_path found in agent_config")
    return None
