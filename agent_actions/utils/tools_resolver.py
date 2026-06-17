"""Resolve tools_path from agent configuration (legacy, simple, and OpenAI formats)."""

import logging
from pathlib import Path
from typing import Any, cast

import yaml

from agent_actions.errors import ConfigValidationError
from agent_actions.utils.path_utils import resolve_relative_to
from agent_actions.utils.project_root import find_project_root

logger = logging.getLogger(__name__)

_FORBIDDEN_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "importlib",
        "ctypes",
        "code",
        "codeop",
        "compile",
        "compileall",
        "socket",
        "http",
        "ftplib",
        "smtplib",
        "telnetlib",
        "pickle",
        "shelve",
        "marshal",
        "builtins",
        "__builtin__",
        "signal",
        "multiprocessing",
        "threading",
    }
)


def _validate_module_path(module_path: str) -> None:
    """Reject module paths that contain traversal or resolve to dangerous stdlib modules."""
    if ".." in module_path or module_path.startswith("/"):
        raise ConfigValidationError(
            f"module_path '{module_path}' contains path traversal — must be a dotted Python name"
        )
    top_level = module_path.split(".")[0]
    if top_level in _FORBIDDEN_MODULES:
        raise ConfigValidationError(
            f"module_path '{module_path}' resolves to a restricted module '{top_level}'"
        )


def anchor_to_project_root(path: str) -> str:
    """Anchor a relative path to the project root, or return as-is if absolute."""
    root = find_project_root()
    if root:
        return str(resolve_relative_to(path, root))
    return path


def resolve_tools_path(agent_config: dict[str, Any]) -> str | None:
    """Resolve tools path from agent config, or None if not found.

    Supports legacy ``tool_path`` (str/list), simple ``tools.path``,
    and OpenAI function-calling ``tools[].function.file`` formats.
    Relative paths are resolved against the detected project root so
    that tool imports work from any working directory.
    """
    tool_path = agent_config.get("tool_path")
    if tool_path:
        if isinstance(tool_path, list) and len(tool_path) > 0:
            logger.debug("Resolved tools_path from tool_path list: %s", tool_path[0])
            return anchor_to_project_root(cast(str, tool_path[0]))
        if isinstance(tool_path, str):
            logger.debug("Resolved tools_path from tool_path string: %s", tool_path)
            return anchor_to_project_root(tool_path)

    tools = agent_config.get("tools", [])

    if isinstance(tools, dict) and "path" in tools:
        path = tools.get("path")
        if isinstance(path, str) and path:
            logger.debug("Resolved tools_path from tools.path: %s", path)
            return anchor_to_project_root(path)
        return None

    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and tool.get("type") == "function":
                function_def = tool.get("function", {})
                if "file" in function_def:
                    try:
                        tool_file_path = function_def["file"]
                        resolved = Path(tool_file_path).resolve()
                        safe_root = find_project_root() or Path.cwd().resolve()
                        try:
                            resolved.relative_to(safe_root)
                        except ValueError as exc:
                            raise ConfigValidationError(
                                f"Tool file path '{tool_file_path}' resolves outside the project root "
                                f"'{safe_root}' — possible path traversal"
                            ) from exc
                        with open(resolved, encoding="utf-8") as f:
                            tool_config = yaml.safe_load(f)
                            if tool_config and "module_path" in tool_config:
                                module_path = str(tool_config["module_path"])
                                _validate_module_path(module_path)
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
