"""
Compatibility shim for guard_parser.

This module provides backward compatibility for imports that expect
'guard_parser' in utilities when it's actually in response_processing.
"""

from agent_actions.response_processing.guard_parser import *

# Explicitly re-export common items to avoid issues
from agent_actions.response_processing.guard_parser import (
    parse_guard,
    GuardParser,
    GuardExpression,
    GuardType,
)

__all__ = ['parse_guard', 'GuardParser', 'GuardExpression', 'GuardType']
