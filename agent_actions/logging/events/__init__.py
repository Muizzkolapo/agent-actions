"""
Agent-actions specific event types.

This module contains event definitions specific to the agent-actions domain.
These events extend the core event infrastructure with workflow, agent,
and LLM-specific events.
"""

from agent_actions.logging.events.types import (
    # Workflow events
    WorkflowStartEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    # Agent events
    AgentStartEvent,
    AgentCompleteEvent,
    AgentSkipEvent,
    AgentFailedEvent,
    AgentCachedEvent,
    # Batch events
    BatchSubmittedEvent,
    BatchProgressEvent,
    BatchCompleteEvent,
    # LLM events
    LLMRequestEvent,
    LLMResponseEvent,
    LLMErrorEvent,
    RateLimitEvent,
    # Validation events
    ValidationStartEvent,
    ValidationCompleteEvent,
    ValidationErrorEvent,
    ValidationWarningEvent,
    # Event categories
    EventCategories,
)
from agent_actions.logging.events.formatters import AgentActionsFormatter

__all__ = [
    # Workflow
    "WorkflowStartEvent",
    "WorkflowCompleteEvent",
    "WorkflowFailedEvent",
    # Agent
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentSkipEvent",
    "AgentFailedEvent",
    "AgentCachedEvent",
    # Batch
    "BatchSubmittedEvent",
    "BatchProgressEvent",
    "BatchCompleteEvent",
    # LLM
    "LLMRequestEvent",
    "LLMResponseEvent",
    "LLMErrorEvent",
    "RateLimitEvent",
    # Validation
    "ValidationStartEvent",
    "ValidationCompleteEvent",
    "ValidationErrorEvent",
    "ValidationWarningEvent",
    # Categories
    "EventCategories",
    # Formatter
    "AgentActionsFormatter",
]
