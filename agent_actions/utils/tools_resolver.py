"""Resolve tools_path from an agent's ``tool_path``."""

import logging
from typing import Any, cast

from agent_actions.utils.path_utils import resolve_relative_to
from agent_actions.utils.project_root import find_project_root

logger = logging.getLogger(__name__)


def parse_udf_call(call_args: str) -> tuple[str, str, list[str]]:
    """Split a ``dispatch_task('module.function, arg, ...')`` argument string.

    Returns ``(module_name, function_name, args)``. A bare name is both the module and
    the function.
    """
    args = [arg.strip().strip("'\"") for arg in call_args.split(",")]
    full_name, function_args = args[0], args[1:]
    if "." in full_name:
        module_name, function_name = full_name.rsplit(".", 1)
    else:
        module_name = function_name = full_name
    return module_name, function_name, function_args


def anchor_to_project_root(path: str) -> str:
    """Anchor a relative path to the project root, or return as-is if absolute."""
    root = find_project_root()
    if root:
        return str(resolve_relative_to(path, root))
    return path


def resolve_tools_path(agent_config: dict[str, Any]) -> str | None:
    """The first ``tool_path`` entry, anchored to the project root, or None.

    A relative path is resolved against the detected project root so that tool
    imports work from any working directory.
    """
    tool_path = agent_config.get("tool_path")
    if isinstance(tool_path, list) and tool_path:
        logger.debug("Resolved tools_path from tool_path list: %s", tool_path[0])
        return anchor_to_project_root(cast(str, tool_path[0]))
    if isinstance(tool_path, str) and tool_path:
        logger.debug("Resolved tools_path from tool_path string: %s", tool_path)
        return anchor_to_project_root(tool_path)

    logger.debug("No tools_path found in agent_config")
    return None
