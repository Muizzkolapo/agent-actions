"""Agent-actions specific event types."""

from agent_actions.logging.events.formatters import AgentActionsFormatter
from agent_actions.logging.events.types import (
    AgentCachedEvent,
    AgentCompleteEvent,
    AgentFailedEvent,
    AgentSkipEvent,
    # Agent events
    AgentStartEvent,
    ApplicationInitializationStartEvent,
    BatchCompleteEvent,
    BatchDataProcessingCompleteEvent,
    BatchErrorEvent,
    BatchPartialFailureEvent,
    BatchPassthroughEvent,
    BatchProcessingCompleteEvent,
    BatchProcessingProgressEvent,
    # Batch Processing events (data processing)
    BatchProcessingStartedEvent,
    BatchProgressEvent,
    BatchResultProcessingFailedEvent,
    BatchResultsProcessedEvent,
    BatchStatusCheckFailedEvent,
    BatchStatusEvent,
    BatchSubmissionFailedEvent,
    # Batch events
    BatchSubmittedEvent,
    # Cache events
    CacheHitEvent,
    CacheInvalidationEvent,
    CacheLoadEvent,
    CacheMissEvent,
    CacheStatsEvent,
    CacheUpdateEvent,
    CLIArgumentParsingEvent,
    CLIInitCompleteEvent,
    # Initialization events (CLI, System, Project)
    CLIInitStartEvent,
    ConfigLoadCompleteEvent,
    ConfigLoadEvent,
    # Configuration events
    ConfigLoadStartEvent,
    ConfigValidationEvent,
    ContextDependencyInferredEvent,
    ContextFieldNotFoundEvent,
    ContextFieldSkippedEvent,
    # Context introspection events
    ContextNamespaceLoadedEvent,
    ContextScopeAppliedEvent,
    DataLoadingErrorEvent,
    DataNormalizationStartedEvent,
    DataNormalizedEvent,
    # Data events
    DataParsingErrorEvent,
    DataValidationErrorEvent,
    DataValidationFailedEvent,
    DataValidationPassedEvent,
    # Data validation events
    DataValidationStartedEvent,
    DIContainerInitializationEvent,
    EnricherExecutedEvent,
    EnrichmentPipelineCompleteEvent,
    # Data transformation events
    EnrichmentPipelineStartedEvent,
    EnvironmentLoadCompleteEvent,
    # Environment events
    EnvironmentLoadStartEvent,
    EnvironmentVariableDetectedEvent,
    # Event categories
    EventCategories,
    ExhaustedRecordEvent,
    FileWriteCompleteEvent,
    FileWriteStartedEvent,
    GuardEvaluationErrorEvent,
    # Guard events
    GuardEvaluationTimeoutEvent,
    LLMConnectionErrorEvent,
    LLMErrorEvent,
    LLMJSONParseErrorEvent,
    # LLM events
    LLMRequestEvent,
    LLMResponseEvent,
    LLMServerErrorEvent,
    ProcessorRegistrationEvent,
    ProjectDirectoryCreatedEvent,
    ProjectInitializationStartEvent,
    ProjectInitializedEvent,
    ProjectValidationEvent,
    RateLimitEvent,
    RecordEmptyOutputEvent,
    RecordFilteredEvent,
    RecordProcessingCompleteEvent,
    # Record Processing Pipeline events
    RecordProcessingStartedEvent,
    RecordTransformedEvent,
    RecoveryErrorEvent,
    RepromptValidationFailedEvent,
    ResultCollectedEvent,
    ResultCollectionCompleteEvent,
    # Result Collection events
    ResultCollectionStartedEvent,
    # Recovery events
    RetryExhaustedEvent,
    SchemaConstructionCompleteEvent,
    # Schema operation events
    SchemaConstructionStartedEvent,
    SchemaLoadedEvent,
    SchemaLoadingStartedEvent,
    SourceDataSavedEvent,
    # File I/O events
    SourceDataSavingEvent,
    StartupValidationCompleteEvent,
    StartupValidationStartEvent,
    # Template events
    TemplateRenderingFailedEvent,
    TemplateSyntaxErrorEvent,
    UDFDiscoveredEvent,
    UDFDiscoveryCompleteEvent,
    # Plugin/UDF events
    UDFDiscoveryStartEvent,
    ValidationCompleteEvent,
    ValidationErrorEvent,
    # Validation events
    ValidationStartEvent,
    ValidationWarningEvent,
    WorkflowCompleteEvent,
    WorkflowFailedEvent,
    WorkflowInitializationStartEvent,
    WorkflowServicesInitializationStartEvent,
    # Workflow events
    WorkflowStartEvent,
)

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
    "RecordEmptyOutputEvent",
    # Batch Processing (data processing)
    "BatchProcessingStartedEvent",
    "BatchProcessingProgressEvent",
    "BatchDataProcessingCompleteEvent",
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
