"""Main pipeline implementation."""

from typing import Any, Dict, List, Optional
from datetime import datetime
import asyncio
import logging

from .interfaces import (
    IPipeline,
    IPipelineStage,
    PipelineContext,
    StageResult,
    StageStatus,
    ValidationError,
    TransformationError
)


logger = logging.getLogger(__name__)


class Pipeline(IPipeline):
    """
    Main pipeline implementation that orchestrates data flow through stages.
    
    This implementation ensures:
    - Pure function transformations (no side effects)
    - Clear error handling and reporting
    - Stage isolation and composability
    - Comprehensive validation between stages
    """
    
    def __init__(self, name: str, description: str = ""):
        """
        Initialize a new pipeline.
        
        Args:
            name: Name of the pipeline
            description: Optional description of the pipeline's purpose
        """
        self.name = name
        self.description = description
        self._stages: List[IPipelineStage] = []
        self._error_handlers: Dict[str, callable] = {}
        self._stage_interceptors: Dict[str, List[callable]] = {}
    
    def add_stage(self, stage: IPipelineStage) -> 'Pipeline':
        """
        Add a stage to the pipeline.
        
        Args:
            stage: Stage to add
            
        Returns:
            Self for method chaining
        """
        # Check for duplicate stage names
        if any(s.name == stage.name for s in self._stages):
            raise ValueError(f"Stage with name '{stage.name}' already exists in pipeline")
        
        self._stages.append(stage)
        logger.info(f"Added stage '{stage.name}' to pipeline '{self.name}'")
        return self
    
    def remove_stage(self, stage_name: str) -> 'Pipeline':
        """
        Remove a stage from the pipeline.
        
        Args:
            stage_name: Name of stage to remove
            
        Returns:
            Self for method chaining
        """
        self._stages = [s for s in self._stages if s.name != stage_name]
        # Clean up associated handlers and interceptors
        self._error_handlers.pop(stage_name, None)
        self._stage_interceptors.pop(stage_name, None)
        logger.info(f"Removed stage '{stage_name}' from pipeline '{self.name}'")
        return self
    
    def add_error_handler(self, stage_name: str, handler: callable) -> 'Pipeline':
        """
        Add an error handler for a specific stage.
        
        Args:
            stage_name: Name of the stage
            handler: Error handler function
            
        Returns:
            Self for method chaining
        """
        self._error_handlers[stage_name] = handler
        return self
    
    def add_stage_interceptor(self, stage_name: str, interceptor: callable) -> 'Pipeline':
        """
        Add an interceptor that runs before a specific stage.
        
        Args:
            stage_name: Name of the stage
            interceptor: Interceptor function
            
        Returns:
            Self for method chaining
        """
        if stage_name not in self._stage_interceptors:
            self._stage_interceptors[stage_name] = []
        self._stage_interceptors[stage_name].append(interceptor)
        return self
    
    def execute(self, data: Any, metadata: Optional[Dict[str, Any]] = None) -> PipelineContext:
        """
        Execute the pipeline on input data.
        
        Args:
            data: Input data to process
            metadata: Optional metadata for the pipeline context
            
        Returns:
            Final pipeline context with results
        """
        context = PipelineContext(
            data=data,
            metadata=metadata or {},
            stage_results=[]
        )
        
        # Add pipeline metadata
        context.set_metadata('pipeline_name', self.name)
        context.set_metadata('pipeline_start_time', datetime.now())
        
        try:
            for stage in self._stages:
                context = self._execute_stage(stage, context)
                
        except (ValidationError, TransformationError) as e:
            # These are already properly formatted, just re-raise
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise TransformationError(
                f"Unexpected error in pipeline '{self.name}'",
                stage_name="pipeline",
                original_error=e
            )
        finally:
            context.set_metadata('pipeline_end_time', datetime.now())
        
        return context
    
    async def execute_async(self, data: Any, metadata: Optional[Dict[str, Any]] = None) -> PipelineContext:
        """
        Execute the pipeline asynchronously.
        
        Args:
            data: Input data to process
            metadata: Optional metadata for the pipeline context
            
        Returns:
            Final pipeline context with results
        """
        context = PipelineContext(
            data=data,
            metadata=metadata or {},
            stage_results=[]
        )
        
        # Add pipeline metadata
        context.set_metadata('pipeline_name', self.name)
        context.set_metadata('pipeline_start_time', datetime.now())
        
        try:
            for stage in self._stages:
                context = await self._execute_stage_async(stage, context)
                
        except (ValidationError, TransformationError) as e:
            # These are already properly formatted, just re-raise
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise TransformationError(
                f"Unexpected error in async pipeline '{self.name}'",
                stage_name="pipeline",
                original_error=e
            )
        finally:
            context.set_metadata('pipeline_end_time', datetime.now())
        
        return context
    
    def _execute_stage(self, stage: IPipelineStage, context: PipelineContext) -> PipelineContext:
        """Execute a single stage synchronously."""
        start_time = datetime.now()
        result = StageResult(
            stage_name=stage.name,
            status=StageStatus.RUNNING,
            data=None,
            start_time=start_time
        )
        
        try:
            # Run interceptors
            self._run_interceptors(stage.name, context)
            
            # Validate input
            validation_errors = stage.validate_input(context.data)
            if validation_errors:
                raise ValidationError(
                    f"Input validation failed for stage '{stage.name}'",
                    stage_name=stage.name,
                    errors=validation_errors
                )
            
            # Transform data
            transformed_data = stage.transform(context.data, context)
            
            # Validate output
            output_errors = stage.validate_output(transformed_data)
            if output_errors:
                raise ValidationError(
                    f"Output validation failed for stage '{stage.name}'",
                    stage_name=stage.name,
                    errors=output_errors
                )
            
            # Update context with successful result
            result.status = StageStatus.SUCCESS
            result.data = transformed_data
            result.end_time = datetime.now()
            context.data = transformed_data
            context.add_result(result)
            
            logger.info(f"Stage '{stage.name}' completed successfully in {result.duration:.3f}s")
            
        except Exception as e:
            result.status = StageStatus.FAILED
            result.error = e
            result.end_time = datetime.now()
            context.add_result(result)
            
            # Try custom error handler
            if stage.name in self._error_handlers:
                try:
                    handled_context = self._error_handlers[stage.name](e, context)
                    if handled_context:
                        return handled_context
                except Exception as handler_error:
                    logger.error(f"Error handler for stage '{stage.name}' failed: {handler_error}")
            
            # Re-raise the original error
            raise
        
        return context
    
    async def _execute_stage_async(self, stage: IPipelineStage, context: PipelineContext) -> PipelineContext:
        """Execute a single stage asynchronously."""
        start_time = datetime.now()
        result = StageResult(
            stage_name=stage.name,
            status=StageStatus.RUNNING,
            data=None,
            start_time=start_time
        )
        
        try:
            # Run interceptors
            await self._run_interceptors_async(stage.name, context)
            
            # Validate input
            validation_errors = stage.validate_input(context.data)
            if validation_errors:
                raise ValidationError(
                    f"Input validation failed for stage '{stage.name}'",
                    stage_name=stage.name,
                    errors=validation_errors
                )
            
            # Transform data
            transformed_data = await stage.transform_async(context.data, context)
            
            # Validate output
            output_errors = stage.validate_output(transformed_data)
            if output_errors:
                raise ValidationError(
                    f"Output validation failed for stage '{stage.name}'",
                    stage_name=stage.name,
                    errors=output_errors
                )
            
            # Update context with successful result
            result.status = StageStatus.SUCCESS
            result.data = transformed_data
            result.end_time = datetime.now()
            context.data = transformed_data
            context.add_result(result)
            
            logger.info(f"Stage '{stage.name}' completed successfully in {result.duration:.3f}s")
            
        except Exception as e:
            result.status = StageStatus.FAILED
            result.error = e
            result.end_time = datetime.now()
            context.add_result(result)
            
            # Try custom error handler
            if stage.name in self._error_handlers:
                try:
                    handled_context = await asyncio.to_thread(
                        self._error_handlers[stage.name], e, context
                    )
                    if handled_context:
                        return handled_context
                except Exception as handler_error:
                    logger.error(f"Error handler for stage '{stage.name}' failed: {handler_error}")
            
            # Re-raise the original error
            raise
        
        return context
    
    def _run_interceptors(self, stage_name: str, context: PipelineContext):
        """Run interceptors for a stage."""
        if stage_name in self._stage_interceptors:
            for interceptor in self._stage_interceptors[stage_name]:
                interceptor(context)
    
    async def _run_interceptors_async(self, stage_name: str, context: PipelineContext):
        """Run interceptors for a stage asynchronously."""
        if stage_name in self._stage_interceptors:
            for interceptor in self._stage_interceptors[stage_name]:
                if asyncio.iscoroutinefunction(interceptor):
                    await interceptor(context)
                else:
                    await asyncio.to_thread(interceptor, context)
    
    def get_stages(self) -> List[IPipelineStage]:
        """Get all stages in the pipeline."""
        return self._stages.copy()
    
    def validate_pipeline(self) -> List[Dict[str, Any]]:
        """
        Validate the pipeline configuration.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check if pipeline has at least one stage
        if not self._stages:
            errors.append({
                'type': 'pipeline_error',
                'message': 'Pipeline must have at least one stage'
            })
        
        # Check for stage name conflicts
        stage_names = [s.name for s in self._stages]
        if len(stage_names) != len(set(stage_names)):
            errors.append({
                'type': 'pipeline_error',
                'message': 'Duplicate stage names found'
            })
        
        # Validate error handlers reference existing stages
        for handler_stage in self._error_handlers:
            if handler_stage not in stage_names:
                errors.append({
                    'type': 'pipeline_error',
                    'message': f"Error handler references non-existent stage '{handler_stage}'"
                })
        
        # Validate interceptors reference existing stages
        for interceptor_stage in self._stage_interceptors:
            if interceptor_stage not in stage_names:
                errors.append({
                    'type': 'pipeline_error',
                    'message': f"Interceptor references non-existent stage '{interceptor_stage}'"
                })
        
        return errors
    
    def __repr__(self):
        """String representation of the pipeline."""
        stage_names = [s.name for s in self._stages]
        return f"Pipeline(name='{self.name}', stages={stage_names})"