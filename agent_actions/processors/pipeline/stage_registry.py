"""Registry for pipeline stages."""

from typing import Dict, Type, List, Optional
import logging

from .interfaces import IPipelineStage


logger = logging.getLogger(__name__)


class StageRegistry:
    """
    Registry for managing pipeline stages.
    
    This allows for:
    - Dynamic stage registration
    - Stage discovery
    - Stage factory pattern
    """
    
    _instance = None
    _stages: Dict[str, Type[IPipelineStage]] = {}
    
    def __new__(cls):
        """Singleton pattern for global registry."""
        if cls._instance is None:
            cls._instance = super(StageRegistry, cls).__new__(cls)
        return cls._instance
    
    @classmethod
    def register(cls, name: str, stage_class: Type[IPipelineStage]):
        """
        Register a stage class.
        
        Args:
            name: Name to register the stage under
            stage_class: Stage class to register
        """
        if name in cls._stages:
            logger.warning(f"Overwriting existing stage registration for '{name}'")
        
        cls._stages[name] = stage_class
        logger.info(f"Registered stage '{name}' -> {stage_class.__name__}")
    
    @classmethod
    def unregister(cls, name: str):
        """
        Unregister a stage.
        
        Args:
            name: Name of stage to unregister
        """
        if name in cls._stages:
            del cls._stages[name]
            logger.info(f"Unregistered stage '{name}'")
    
    @classmethod
    def get(cls, name: str) -> Optional[Type[IPipelineStage]]:
        """
        Get a registered stage class.
        
        Args:
            name: Name of the stage
            
        Returns:
            Stage class or None if not found
        """
        return cls._stages.get(name)
    
    @classmethod
    def create_stage(cls, name: str, *args, **kwargs) -> IPipelineStage:
        """
        Create an instance of a registered stage.
        
        Args:
            name: Name of the stage
            *args: Positional arguments for stage constructor
            **kwargs: Keyword arguments for stage constructor
            
        Returns:
            Stage instance
            
        Raises:
            ValueError: If stage not found
        """
        stage_class = cls.get(name)
        if not stage_class:
            raise ValueError(f"Stage '{name}' not found in registry")
        
        return stage_class(*args, **kwargs)
    
    @classmethod
    def list_stages(cls) -> List[str]:
        """Get list of all registered stage names."""
        return list(cls._stages.keys())
    
    @classmethod
    def clear(cls):
        """Clear all registered stages."""
        cls._stages.clear()
        logger.info("Cleared stage registry")


def register_stage(name: str):
    """
    Decorator to register a stage class.
    
    Usage:
        @register_stage("my_stage")
        class MyStage(IPipelineStage):
            ...
    """
    def decorator(stage_class: Type[IPipelineStage]):
        StageRegistry.register(name, stage_class)
        return stage_class
    return decorator