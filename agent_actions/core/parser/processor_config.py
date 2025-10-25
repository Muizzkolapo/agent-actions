"""Processor configuration models for standardized configuration management."""

from pydantic import BaseModel, Field, field_validator
from typing import Dict, Optional, Literal
from enum import Enum


class ProcessingMode(str, Enum):
    """Processing modes supported by processors."""
    SYNC = "sync"
    ASYNC = "async"
    AUTO = "auto"


class CacheStrategy(str, Enum):
    """Cache strategies for processors."""
    NONE = "none"
    MEMORY = "memory"
    REDIS = "redis"
    FILE = "file"


class ProcessorConfig(BaseModel):
    """Base configuration for all processors."""
    
    name: str = Field(..., description="Processor name/identifier")
    enabled: bool = Field(default=True, description="Whether processor is enabled")
    processing_mode: ProcessingMode = Field(
        default=ProcessingMode.AUTO,
        description="Processing mode for the processor"
    )
    max_workers: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of worker threads/processes"
    )
    timeout: int = Field(
        default=300,
        ge=1,
        description="Processing timeout in seconds"
    )
    retry_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Number of retry attempts on failure"
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0.0,
        description="Delay between retries in seconds"
    )
    
    model_config = {"extra": "allow"}


class CacheConfig(BaseModel):
    """Cache configuration for processors."""
    
    enabled: bool = Field(default=True, description="Enable caching")
    strategy: CacheStrategy = Field(
        default=CacheStrategy.MEMORY,
        description="Caching strategy to use"
    )
    ttl: int = Field(
        default=300,
        ge=0,
        description="Cache TTL in seconds (0 for no expiration)"
    )
    max_size: Optional[int] = Field(
        default=1000,
        ge=1,
        description="Maximum cache size (strategy dependent)"
    )
    key_prefix: str = Field(
        default="processor",
        description="Prefix for cache keys"
    )
    
    # Redis-specific settings
    redis_url: Optional[str] = Field(
        default=None,
        description="Redis connection URL (for Redis strategy)"
    )
    
    # File-specific settings
    cache_dir: Optional[str] = Field(
        default=None,
        description="Directory for file cache (for File strategy)"
    )


class DataProcessorConfig(ProcessorConfig):
    """Configuration specific to data processors."""
    
    transformation_enabled: bool = Field(
        default=True,
        description="Enable data transformations"
    )
    validation_enabled: bool = Field(
        default=True,
        description="Enable data validation"
    )
    observe_handling: Literal["ignore", "separate", "merge"] = Field(
        default="separate",
        description="How to handle observe fields"
    )
    cache_config: Optional[CacheConfig] = Field(
        default=None,
        description="Cache configuration for data processor"
    )


class GeneratorConfig(ProcessorConfig):
    """Configuration specific to data generators."""
    
    agent_creation_timeout: int = Field(
        default=60,
        ge=1,
        description="Timeout for agent creation in seconds"
    )
    prompt_caching_enabled: bool = Field(
        default=True,
        description="Enable prompt caching for performance"
    )
    few_shot_samples_limit: int = Field(
        default=10,
        ge=0,
        description="Maximum number of few-shot samples"
    )
    dynamic_agent_enabled: bool = Field(
        default=True,
        description="Enable dynamic agent creation"
    )


class ContentProcessorConfig(ProcessorConfig):
    """Configuration for content processors."""
    
    batch_size: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Batch size for content processing"
    )
    parallel_processing: bool = Field(
        default=True,
        description="Enable parallel processing of content"
    )
    error_handling_strategy: Literal["fail_fast", "skip_errors", "collect_errors"] = Field(
        default="collect_errors",
        description="Strategy for handling processing errors"
    )
    max_content_size: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum content size in bytes (None for unlimited)"
    )


class BatchProcessorConfig(BaseModel):
    """Configuration for batch processing operations."""
    
    default_batch_size: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Default batch size for operations"
    )
    max_batch_size: int = Field(
        default=1000,
        ge=1,
        description="Maximum allowed batch size"
    )
    batch_timeout: int = Field(
        default=600,
        ge=1,
        description="Timeout for batch operations in seconds"
    )
    parallel_batches: bool = Field(
        default=True,
        description="Enable parallel batch processing"
    )
    max_concurrent_batches: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of concurrent batches"
    )
    
    @field_validator('max_batch_size')
    @classmethod
    def validate_max_batch_size(cls, v, info):
        """Ensure max_batch_size is not smaller than default_batch_size."""
        from agent_actions.core.exceptions import ConfigValidationError

        if 'default_batch_size' in info.data and v < info.data['default_batch_size']:
            raise ConfigValidationError(
                "max_batch_size",
                "max_batch_size must be >= default_batch_size",
                context={'max_batch_size': v, 'default_batch_size': info.data['default_batch_size'], 'operation': 'validate_batch_config'}
            )
        return v


class ProcessorRegistryConfig(BaseModel):
    """Configuration for the processor registry."""
    
    data_processors: Dict[str, DataProcessorConfig] = Field(
        default_factory=dict,
        description="Registered data processors configuration"
    )
    generators: Dict[str, GeneratorConfig] = Field(
        default_factory=dict,
        description="Registered generators configuration"
    )
    content_processors: Dict[str, ContentProcessorConfig] = Field(
        default_factory=dict,
        description="Registered content processors configuration"
    )
    batch_config: BatchProcessorConfig = Field(
        default_factory=BatchProcessorConfig,
        description="Batch processing configuration"
    )
    cache_config: CacheConfig = Field(
        default_factory=CacheConfig,
        description="Global cache configuration"
    )
    
    def get_processor_config(self, processor_type: str, processor_name: str) -> Optional[ProcessorConfig]:
        """Get configuration for a specific processor."""
        if processor_type == "data_processor":
            return self.data_processors.get(processor_name)
        elif processor_type == "generator":
            return self.generators.get(processor_name)
        elif processor_type == "content_processor":
            return self.content_processors.get(processor_name)
        return None


__all__ = [
    "ProcessorConfig",
    "CacheConfig",
    "DataProcessorConfig", 
    "GeneratorConfig",
    "ContentProcessorConfig",
    "BatchProcessorConfig",
    "ProcessorRegistryConfig",
    "ProcessingMode",
    "CacheStrategy",
]