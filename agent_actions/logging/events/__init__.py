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
    BatchProcessingCompleteEvent,
    BatchResultsProcessedEvent,
    BatchErrorEvent,
    BatchPassthroughEvent,
    BatchStatusEvent,
    BatchSubmissionFailedEvent,
    BatchStatusCheckFailedEvent,
    BatchResultProcessingFailedEvent,
    BatchPartialFailureEvent,
    # LLM events
    LLMRequestEvent,
    LLMResponseEvent,
    LLMErrorEvent,
    RateLimitEvent,
    LLMJSONParseErrorEvent,
    LLMConnectionErrorEvent,
    LLMServerErrorEvent,
    # Validation events
    ValidationStartEvent,
    ValidationCompleteEvent,
    ValidationErrorEvent,
    ValidationWarningEvent,
    # Cache events
    CacheHitEvent,
    CacheMissEvent,
    CacheInvalidationEvent,
    CacheLoadEvent,
    CacheUpdateEvent,
    CacheStatsEvent,
    # Template events
    TemplateRenderingFailedEvent,
    TemplateSyntaxErrorEvent,
    # Data events
    DataParsingErrorEvent,
    DataLoadingErrorEvent,
    DataValidationErrorEvent,
    # Guard events
    GuardEvaluationTimeoutEvent,
    GuardEvaluationErrorEvent,
    # Recovery events
    RetryExhaustedEvent,
    RepromptValidationFailedEvent,
    RecoveryErrorEvent,
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
    "BatchProcessingCompleteEvent",
    "BatchResultsProcessedEvent",
    "BatchErrorEvent",
    "BatchPassthroughEvent",
    "BatchStatusEvent",
    "BatchSubmissionFailedEvent",
    "BatchStatusCheckFailedEvent",
    "BatchResultProcessingFailedEvent",
    "BatchPartialFailureEvent",
    # LLM
    "LLMRequestEvent",
    "LLMResponseEvent",
    "LLMErrorEvent",
    "RateLimitEvent",
    "LLMJSONParseErrorEvent",
    "LLMConnectionErrorEvent",
    "LLMServerErrorEvent",
    # Validation
    "ValidationStartEvent",
    "ValidationCompleteEvent",
    "ValidationErrorEvent",
    "ValidationWarningEvent",
    # Cache
    "CacheHitEvent",
    "CacheMissEvent",
    "CacheInvalidationEvent",
    "CacheLoadEvent",
    "CacheUpdateEvent",
    "CacheStatsEvent",
    # Template
    "TemplateRenderingFailedEvent",
    "TemplateSyntaxErrorEvent",
    # Data
    "DataParsingErrorEvent",
    "DataLoadingErrorEvent",
    "DataValidationErrorEvent",
    # Guard
    "GuardEvaluationTimeoutEvent",
    "GuardEvaluationErrorEvent",
    # Recovery
    "RetryExhaustedEvent",
    "RepromptValidationFailedEvent",
    "RecoveryErrorEvent",
    # Categories
    "EventCategories",
    # Formatter
    "AgentActionsFormatter",
]
