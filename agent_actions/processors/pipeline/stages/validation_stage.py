"""Validation stage for data pipeline."""

from typing import Any, Dict, List, Callable, Optional
import json
from jsonschema import validate, ValidationError as JsonSchemaError

from .base_stage import BaseStage
from ..interfaces import PipelineContext, TransformationError
from ..stage_registry import register_stage


@register_stage("validation")
class ValidationStage(BaseStage):
    """
    Stage that validates data against a schema or custom rules.
    
    This stage performs validation without modifying the data.
    It's a pure function that only checks data validity.
    """
    
    def __init__(
        self,
        name: str = "validation",
        description: str = "Validates data structure and content",
        schema: Optional[Dict[str, Any]] = None,
        custom_validators: Optional[List[Callable[[Any], List[Dict[str, Any]]]]] = None,
        strict: bool = True
    ):
        """
        Initialize validation stage.
        
        Args:
            name: Name of the stage
            description: Description of the stage
            schema: JSON schema for validation (optional)
            custom_validators: List of custom validation functions
            strict: Whether to fail on validation errors (True) or just log them (False)
        """
        super().__init__(name, description)
        self.schema = schema
        self.custom_validators = custom_validators or []
        self.strict = strict
    
    def validate_input(self, data: Any) -> List[Dict[str, Any]]:
        """Validate input data."""
        errors = []
        
        # Check if data is None
        if data is None:
            errors.append({
                'field': 'data',
                'message': 'Input data cannot be None',
                'type': 'null_error'
            })
            return errors
        
        # Run schema validation if provided
        if self.schema:
            try:
                validate(instance=data, schema=self.schema)
            except JsonSchemaError as e:
                errors.append({
                    'field': e.path,
                    'message': e.message,
                    'type': 'schema_error'
                })
        
        # Run custom validators
        for validator in self.custom_validators:
            validator_errors = validator(data)
            errors.extend(validator_errors)
        
        return errors
    
    def transform(self, data: Any, context: PipelineContext) -> Any:
        """
        Validate data without transformation.
        
        Args:
            data: Input data to validate
            context: Pipeline context
            
        Returns:
            Original data if validation passes
            
        Raises:
            TransformationError: If validation fails and strict mode is enabled
        """
        validation_errors = self.validate_input(data)
        
        if validation_errors:
            error_message = f"Validation failed with {len(validation_errors)} errors"
            
            # Store errors in context metadata
            context.set_metadata(f"{self.name}_errors", validation_errors)
            
            if self.strict:
                raise TransformationError(
                    error_message,
                    stage_name=self.name
                )
            else:
                # Log errors but continue
                context.set_metadata(f"{self.name}_status", "failed_non_strict")
        else:
            context.set_metadata(f"{self.name}_status", "passed")
        
        # Return data unchanged
        return data


class SchemaValidationBuilder:
    """Builder for creating schema validation stages."""
    
    def __init__(self, name: str = "schema_validation"):
        self.name = name
        self.description = "Validates data against schema"
        self.schema = None
        self.custom_validators = []
        self.strict = True
    
    def with_schema(self, schema: Dict[str, Any]) -> 'SchemaValidationBuilder':
        """Add JSON schema for validation."""
        self.schema = schema
        return self
    
    def with_custom_validator(self, validator: Callable[[Any], List[Dict[str, Any]]]) -> 'SchemaValidationBuilder':
        """Add custom validator function."""
        self.custom_validators.append(validator)
        return self
    
    def with_strict_mode(self, strict: bool) -> 'SchemaValidationBuilder':
        """Set strict mode (fail on errors vs log only)."""
        self.strict = strict
        return self
    
    def build(self) -> ValidationStage:
        """Build the validation stage."""
        return ValidationStage(
            name=self.name,
            description=self.description,
            schema=self.schema,
            custom_validators=self.custom_validators,
            strict=self.strict
        )