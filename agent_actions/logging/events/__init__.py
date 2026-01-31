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
    # Configuration events
    ConfigLoadStartEvent,
    ConfigLoadEvent,
    ConfigLoadCompleteEvent,
    ConfigValidationEvent,
    # Environment events
    EnvironmentLoadStartEvent,
    EnvironmentVariableDetectedEvent,
    EnvironmentLoadCompleteEvent,
    # Initialization events (CLI, System, Project)
    CLIInitStartEvent,
    CLIArgumentParsingEvent,
    CLIInitCompleteEvent,
    ApplicationInitializationStartEvent,
    StartupValidationStartEvent,
    StartupValidationCompleteEvent,
    DIContainerInitializationEvent,
    WorkflowInitializationStartEvent,
    WorkflowServicesInitializationStartEvent,
    ProjectInitializationStartEvent,
    ProjectValidationEvent,
    ProjectDirectoryCreatedEvent,
    ProjectInitializedEvent,
    # Plugin/UDF events
    UDFDiscoveryStartEvent,
    UDFDiscoveredEvent,
    UDFDiscoveryCompleteEvent,
    ProcessorRegistrationEvent,
    # File I/O events
    SourceDataSavingEvent,
    SourceDataSavedEvent,
    SchemaLoadingStartedEvent,
    SchemaLoadedEvent,
    FileWriteStartedEvent,
    FileWriteCompleteEvent,
    # Schema operation events
    SchemaConstructionStartedEvent,
    SchemaConstructionCompleteEvent,
    # Data validation events
    DataValidationStartedEvent,
    DataValidationPassedEvent,
    DataValidationFailedEvent,
    # Data transformation events
    EnrichmentPipelineStartedEvent,
    EnricherExecutedEvent,
    EnrichmentPipelineCompleteEvent,
    DataNormalizationStartedEvent,
    DataNormalizedEvent,
    # Record Processing Pipeline events
    RecordProcessingStartedEvent,
    RecordFilteredEvent,
    RecordTransformedEvent,
    RecordProcessingCompleteEvent,
    # Batch Processing events (data processing)
    BatchProcessingStartedEvent,
    BatchProcessingProgressEvent,
    BatchProcessingCompleteEvent,
    # Result Collection events
    ResultCollectionStartedEvent,
    ResultCollectedEvent,
    ResultCollectionCompleteEvent,
    ExhaustedRecordEvent,
    # Context introspection events
    ContextNamespaceLoadedEvent,
    ContextFieldSkippedEvent,
    ContextScopeAppliedEvent,
    ContextDependencyInferredEvent,
    ContextFieldNotFoundEvent,
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
    # Configuration
    "ConfigLoadStartEvent",
    "ConfigLoadEvent",
    "ConfigLoadCompleteEvent",
    "ConfigValidationEvent",
    # Environment
    "EnvironmentLoadStartEvent",
    "EnvironmentVariableDetectedEvent",
    "EnvironmentLoadCompleteEvent",
    # Initialization (CLI, System, Project)
    "CLIInitStartEvent",
    "CLIArgumentParsingEvent",
    "CLIInitCompleteEvent",
    "ApplicationInitializationStartEvent",
    "StartupValidationStartEvent",
    "StartupValidationCompleteEvent",
    "DIContainerInitializationEvent",
    "WorkflowInitializationStartEvent",
    "WorkflowServicesInitializationStartEvent",
    "ProjectInitializationStartEvent",
    "ProjectValidationEvent",
    "ProjectDirectoryCreatedEvent",
    "ProjectInitializedEvent",
    # Plugin/UDF
    "UDFDiscoveryStartEvent",
    "UDFDiscoveredEvent",
    "UDFDiscoveryCompleteEvent",
    "ProcessorRegistrationEvent",
    # File I/O
    "SourceDataSavingEvent",
    "SourceDataSavedEvent",
    "SchemaLoadingStartedEvent",
    "SchemaLoadedEvent",
    "FileWriteStartedEvent",
    "FileWriteCompleteEvent",
    # Schema Operations
    "SchemaConstructionStartedEvent",
    "SchemaConstructionCompleteEvent",
    # Data Validation
    "DataValidationStartedEvent",
    "DataValidationPassedEvent",
    "DataValidationFailedEvent",
    # Data Transformation
    "EnrichmentPipelineStartedEvent",
    "EnricherExecutedEvent",
    "EnrichmentPipelineCompleteEvent",
    "DataNormalizationStartedEvent",
    "DataNormalizedEvent",
    # Record Processing Pipeline
    "RecordProcessingStartedEvent",
    "RecordFilteredEvent",
    "RecordTransformedEvent",
    "RecordProcessingCompleteEvent",
    # Batch Processing (data processing)
    "BatchProcessingStartedEvent",
    "BatchProcessingProgressEvent",
    "BatchProcessingCompleteEvent",
    # Result Collection
    "ResultCollectionStartedEvent",
    "ResultCollectedEvent",
    "ResultCollectionCompleteEvent",
    "ExhaustedRecordEvent",
    # Context Introspection
    "ContextNamespaceLoadedEvent",
    "ContextFieldSkippedEvent",
    "ContextScopeAppliedEvent",
    "ContextDependencyInferredEvent",
    "ContextFieldNotFoundEvent",
    # Categories
    "EventCategories",
    # Formatter
    "AgentActionsFormatter",
]
