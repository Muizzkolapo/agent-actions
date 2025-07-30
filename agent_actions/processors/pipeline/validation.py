"""Data flow validation utilities for the pipeline."""

from typing import Any, Dict, List, Optional, Set, Type
import json
from dataclasses import dataclass
from enum import Enum

from .interfaces import IPipelineStage, PipelineContext
from .pipeline import Pipeline


class ValidationLevel(Enum):
    """Validation strictness levels."""
    STRICT = "strict"      # All validations must pass
    MODERATE = "moderate"  # Critical validations must pass
    LENIENT = "lenient"    # Log warnings but don't fail


@dataclass
class SchemaDefinition:
    """Schema definition for data validation."""
    name: str
    schema: Dict[str, Any]
    description: str = ""
    required: bool = True


@dataclass
class FlowValidationResult:
    """Result of data flow validation."""
    is_valid: bool
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    stage_schemas: Dict[str, SchemaDefinition]
    
    def add_error(self, stage: str, message: str, details: Optional[Dict] = None):
        """Add validation error."""
        error = {
            "stage": stage,
            "message": message,
            "type": "error"
        }
        if details:
            error["details"] = details
        self.errors.append(error)
        self.is_valid = False
    
    def add_warning(self, stage: str, message: str, details: Optional[Dict] = None):
        """Add validation warning."""
        warning = {
            "stage": stage,
            "message": message,
            "type": "warning"
        }
        if details:
            warning["details"] = details
        self.warnings.append(warning)


class DataFlowValidator:
    """
    Validates data flow through pipeline stages.
    
    Ensures:
    - Data schema compatibility between stages
    - Required fields are preserved
    - No data loss occurs unintentionally
    - Type consistency is maintained
    """
    
    def __init__(self, validation_level: ValidationLevel = ValidationLevel.MODERATE):
        """
        Initialize validator.
        
        Args:
            validation_level: How strict validation should be
        """
        self.validation_level = validation_level
        self._stage_schemas: Dict[str, SchemaDefinition] = {}
    
    def register_stage_schema(
        self,
        stage_name: str,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None
    ):
        """
        Register expected schemas for a pipeline stage.
        
        Args:
            stage_name: Name of the stage
            input_schema: Expected input schema
            output_schema: Expected output schema
        """
        if input_schema:
            self._stage_schemas[f"{stage_name}_input"] = SchemaDefinition(
                name=f"{stage_name}_input",
                schema=input_schema
            )
        
        if output_schema:
            self._stage_schemas[f"{stage_name}_output"] = SchemaDefinition(
                name=f"{stage_name}_output",
                schema=output_schema
            )
    
    def validate_pipeline_flow(self, pipeline: Pipeline) -> FlowValidationResult:
        """
        Validate the data flow through a pipeline.
        
        Args:
            pipeline: Pipeline to validate
            
        Returns:
            Validation result with errors and warnings
        """
        result = FlowValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            stage_schemas=self._stage_schemas.copy()
        )
        
        stages = pipeline.get_stages()
        
        if not stages:
            result.add_error("pipeline", "Pipeline has no stages")
            return result
        
        # Validate stage connections
        for i in range(len(stages) - 1):
            current_stage = stages[i]
            next_stage = stages[i + 1]
            
            self._validate_stage_connection(
                current_stage, next_stage, result
            )
        
        # Validate required fields preservation
        self._validate_field_preservation(stages, result)
        
        # Validate no unintended data loss
        self._validate_data_integrity(stages, result)
        
        return result
    
    def _validate_stage_connection(
        self,
        current_stage: IPipelineStage,
        next_stage: IPipelineStage,
        result: FlowValidationResult
    ):
        """Validate connection between two stages."""
        # Check if output schema of current matches input schema of next
        current_output_key = f"{current_stage.name}_output"
        next_input_key = f"{next_stage.name}_input"
        
        if current_output_key in self._stage_schemas and next_input_key in self._stage_schemas:
            current_output = self._stage_schemas[current_output_key].schema
            next_input = self._stage_schemas[next_input_key].schema
            
            # Basic compatibility check
            if not self._schemas_compatible(current_output, next_input):
                result.add_error(
                    f"{current_stage.name} -> {next_stage.name}",
                    "Output schema incompatible with next stage input",
                    {
                        "current_output": current_output,
                        "next_input": next_input
                    }
                )
    
    def _validate_field_preservation(
        self,
        stages: List[IPipelineStage],
        result: FlowValidationResult
    ):
        """Validate that required fields are preserved through the pipeline."""
        # Track required fields from the first stage
        first_stage_input = f"{stages[0].name}_input"
        
        if first_stage_input in self._stage_schemas:
            schema = self._stage_schemas[first_stage_input].schema
            required_fields = self._extract_required_fields(schema)
            
            # Check if required fields are preserved in final output
            last_stage_output = f"{stages[-1].name}_output"
            
            if last_stage_output in self._stage_schemas:
                output_schema = self._stage_schemas[last_stage_output].schema
                output_fields = self._extract_all_fields(output_schema)
                
                missing_fields = required_fields - output_fields
                if missing_fields:
                    if self.validation_level == ValidationLevel.STRICT:
                        result.add_error(
                            "field_preservation",
                            f"Required fields lost in pipeline: {missing_fields}"
                        )
                    else:
                        result.add_warning(
                            "field_preservation",
                            f"Required fields may be lost: {missing_fields}"
                        )
    
    def _validate_data_integrity(
        self,
        stages: List[IPipelineStage],
        result: FlowValidationResult
    ):
        """Validate that data integrity is maintained."""
        # Check for stages that might cause data loss
        risky_stages = []
        
        for stage in stages:
            # Check stage name/description for risky operations
            risky_keywords = ["filter", "remove", "drop", "exclude", "extract"]
            stage_info = f"{stage.name} {stage.description}".lower()
            
            if any(keyword in stage_info for keyword in risky_keywords):
                risky_stages.append(stage.name)
        
        if risky_stages:
            result.add_warning(
                "data_integrity",
                f"Stages may cause data loss: {risky_stages}",
                {"stages": risky_stages}
            )
    
    def _schemas_compatible(
        self,
        output_schema: Dict[str, Any],
        input_schema: Dict[str, Any]
    ) -> bool:
        """Check if two schemas are compatible."""
        # Simple compatibility check - can be extended
        output_type = output_schema.get("type", "object")
        input_type = input_schema.get("type", "object")
        
        # Check basic type compatibility
        if output_type != input_type:
            return False
        
        # For objects, check required fields
        if output_type == "object":
            input_required = set(input_schema.get("required", []))
            output_props = set(output_schema.get("properties", {}).keys())
            
            # Input required fields must be available in output
            if not input_required.issubset(output_props):
                return False
        
        return True
    
    def _extract_required_fields(self, schema: Dict[str, Any]) -> Set[str]:
        """Extract required fields from a schema."""
        if schema.get("type") == "object":
            return set(schema.get("required", []))
        return set()
    
    def _extract_all_fields(self, schema: Dict[str, Any]) -> Set[str]:
        """Extract all fields from a schema."""
        if schema.get("type") == "object":
            return set(schema.get("properties", {}).keys())
        return set()


class DataFlowMonitor:
    """
    Monitors data flow through pipeline execution.
    
    Provides insights into:
    - Data shape changes
    - Performance metrics
    - Field usage statistics
    """
    
    def __init__(self):
        """Initialize monitor."""
        self.stage_metrics: Dict[str, Dict[str, Any]] = {}
        self.field_usage: Dict[str, int] = {}
        self.data_shapes: List[Dict[str, Any]] = []
    
    def monitor_stage_execution(
        self,
        stage_name: str,
        input_data: Any,
        output_data: Any,
        duration: float
    ):
        """
        Record metrics for a stage execution.
        
        Args:
            stage_name: Name of the stage
            input_data: Input data to the stage
            output_data: Output data from the stage
            duration: Execution duration in seconds
        """
        metrics = {
            "duration": duration,
            "input_size": self._calculate_data_size(input_data),
            "output_size": self._calculate_data_size(output_data),
            "data_shape_change": self._analyze_shape_change(input_data, output_data)
        }
        
        if stage_name not in self.stage_metrics:
            self.stage_metrics[stage_name] = {
                "executions": 0,
                "total_duration": 0,
                "avg_duration": 0,
                "min_duration": float('inf'),
                "max_duration": 0
            }
        
        # Update metrics
        stage_stats = self.stage_metrics[stage_name]
        stage_stats["executions"] += 1
        stage_stats["total_duration"] += duration
        stage_stats["avg_duration"] = stage_stats["total_duration"] / stage_stats["executions"]
        stage_stats["min_duration"] = min(stage_stats["min_duration"], duration)
        stage_stats["max_duration"] = max(stage_stats["max_duration"], duration)
        
        # Track field usage
        self._track_field_usage(output_data)
        
        # Record data shape
        self.data_shapes.append({
            "stage": stage_name,
            "shape": self._get_data_shape(output_data)
        })
    
    def _calculate_data_size(self, data: Any) -> int:
        """Calculate size of data structure."""
        if isinstance(data, list):
            return len(data)
        elif isinstance(data, dict):
            return 1
        else:
            return 0
    
    def _analyze_shape_change(self, input_data: Any, output_data: Any) -> Dict[str, Any]:
        """Analyze how data shape changed."""
        return {
            "input_type": type(input_data).__name__,
            "output_type": type(output_data).__name__,
            "size_change": self._calculate_data_size(output_data) - self._calculate_data_size(input_data)
        }
    
    def _track_field_usage(self, data: Any):
        """Track which fields are present in the data."""
        if isinstance(data, dict):
            for field in data.keys():
                self.field_usage[field] = self.field_usage.get(field, 0) + 1
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            # Sample first item for field tracking
            for field in data[0].keys():
                self.field_usage[field] = self.field_usage.get(field, 0) + 1
    
    def _get_data_shape(self, data: Any) -> Dict[str, Any]:
        """Get shape information about data."""
        shape = {
            "type": type(data).__name__,
            "size": self._calculate_data_size(data)
        }
        
        if isinstance(data, dict):
            shape["fields"] = list(data.keys())
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            shape["sample_fields"] = list(data[0].keys())
        
        return shape
    
    def get_report(self) -> Dict[str, Any]:
        """Get monitoring report."""
        return {
            "stage_metrics": self.stage_metrics,
            "field_usage": dict(sorted(
                self.field_usage.items(),
                key=lambda x: x[1],
                reverse=True
            )),
            "data_flow": self.data_shapes,
            "summary": {
                "total_stages": len(self.stage_metrics),
                "total_fields_seen": len(self.field_usage),
                "most_used_fields": list(self.field_usage.keys())[:5]
            }
        }