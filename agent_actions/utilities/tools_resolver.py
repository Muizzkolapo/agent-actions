"""
Shared utility for resolving tools_path from agent configuration.

This module provides a unified way to resolve tools_path across both
batch and realtime modes, eliminating duplication and ensuring consistent
behavior.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def resolve_tools_path(agent_config: Dict[str, Any]) -> Optional[str]:
    """
    Resolve tools path from agent config.

    Supports multiple formats for maximum compatibility:
    1. Legacy format: tool_path: ['path1', 'path2'] or tool_path: 'path'
    2. Simple format: tools: {path: '/path/to/tools'}
    3. OpenAI format: tools: [{type: 'function', function: {file: '...'}}]

    Args:
        agent_config: Agent configuration dictionary

    Returns:
        Resolved tools path string, or None if not found

    Examples:
        >>> # Legacy format (list)
        >>> config = {'tool_path': ['tools', 'utils']}
        >>> resolve_tools_path(config)
        'tools'

        >>> # Legacy format (string)
        >>> config = {'tool_path': 'tools'}
        >>> resolve_tools_path(config)
        'tools'

        >>> # Simple format
        >>> config = {'tools': {'path': '/path/to/tools'}}
        >>> resolve_tools_path(config)
        '/path/to/tools'

        >>> # OpenAI format
        >>> config = {'tools': [{'type': 'function', 'function': {'file': 'tool.yaml'}}]}
        >>> resolve_tools_path(config)
        '/path/from/tool/config'
    """
    # Check for legacy tool_path format first (used in agent_actions.yml)
    tool_path = agent_config.get('tool_path')
    if tool_path:
        # If it's a list, return the first path
        if isinstance(tool_path, list) and len(tool_path) > 0:
            logger.debug("Resolved tools_path from tool_path list: %s", tool_path[0])
            return tool_path[0]
        # If it's a string, return it directly
        if isinstance(tool_path, str):
            logger.debug("Resolved tools_path from tool_path string: %s", tool_path)
            return tool_path

    # Check for tools configuration
    tools = agent_config.get('tools', [])

    # Check for simple format (consistent with realtime mode)
    if isinstance(tools, dict) and 'path' in tools:
        path = tools.get('path')
        logger.debug("Resolved tools_path from tools.path: %s", path)
        return path

    # Check for OpenAI tool calling format
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and tool.get('type') == 'function':
                function_def = tool.get('function', {})
                if 'file' in function_def:
                    import yaml
                    try:
                        tool_file_path = function_def['file']
                        with open(tool_file_path, 'r', encoding='utf-8') as f:
                            tool_config = yaml.safe_load(f)
                            if tool_config and 'module_path' in tool_config:
                                module_path = tool_config['module_path']
                                logger.debug("Resolved tools_path from OpenAI tool config: %s", module_path)
                                return module_path
                    except (yaml.YAMLError, FileNotFoundError, PermissionError) as e:
                        logger.warning("Failed to load tool config from %s: %s", tool_file_path, e)

    logger.debug("No tools_path found in agent_config")
    return None
