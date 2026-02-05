"""
Invocation strategies for LLM execution.

Part of Phase 3 (#891): Extract LLM invocation into strategy pattern.

This module provides:
- InvocationResult: Unified result type for immediate/deferred execution
- InvocationStrategy: ABC for different execution strategies
- OnlineStrategy: Synchronous execution with retry/reprompt
- BatchStrategy: Queue tasks for batch API submission
- InvocationStrategyFactory: Create appropriate strategy based on mode
"""

from .result import InvocationResult
from .strategy import BatchProvider, InvocationStrategy
from .online import OnlineStrategy
from .batch import BatchStrategy, BatchSubmissionResult
from .factory import InvocationStrategyFactory

__all__ = [
    "BatchProvider",
    "InvocationResult",
    "InvocationStrategy",
    "OnlineStrategy",
    "BatchStrategy",
    "BatchSubmissionResult",
    "InvocationStrategyFactory",
]
