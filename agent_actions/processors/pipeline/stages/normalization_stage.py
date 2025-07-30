"""Normalization stage for data pipeline."""

from typing import Any, Dict, List, Optional
import re
from datetime import datetime

from .base_stage import BaseStage
from ..interfaces import PipelineContext, TransformationError
from ..stage_registry import register_stage


@register_stage("normalization")
class NormalizationStage(BaseStage):
    """
    Stage that normalizes data to a consistent format.
    
    This stage ensures data consistency by:
    - Converting data types
    - Standardizing formats
    - Cleaning values
    - Applying default values
    """
    
    def __init__(
        self,
        name: str = "normalization",
        description: str = "Normalizes data to consistent format",
        type_conversions: Optional[Dict[str, type]] = None,
        default_values: Optional[Dict[str, Any]] = None,
        field_normalizers: Optional[Dict[str, callable]] = None,
        strip_whitespace: bool = True,
        lowercase_keys: bool = False
    ):
        """
        Initialize normalization stage.
        
        Args:
            name: Name of the stage
            description: Description of the stage
            type_conversions: Dict mapping field names to target types
            default_values: Dict of default values for missing fields
            field_normalizers: Dict of custom normalization functions per field
            strip_whitespace: Whether to strip whitespace from strings
            lowercase_keys: Whether to convert all keys to lowercase
        """
        super().__init__(name, description)
        self.type_conversions = type_conversions or {}
        self.default_values = default_values or {}
        self.field_normalizers = field_normalizers or {}
        self.strip_whitespace = strip_whitespace
        self.lowercase_keys = lowercase_keys
    
    def transform(self, data: Any, context: PipelineContext) -> Any:
        """
        Normalize the input data.
        
        Args:
            data: Input data to normalize
            context: Pipeline context
            
        Returns:
            Normalized data
            
        Raises:
            TransformationError: If normalization fails
        """
        try:
            if isinstance(data, list):
                return [self._normalize_item(item) for item in data]
            else:
                return self._normalize_item(data)
                
        except Exception as e:
            raise TransformationError(
                f"Normalization failed: {str(e)}",
                stage_name=self.name,
                original_error=e
            )
    
    def _normalize_item(self, item: Any) -> Any:
        """Normalize a single data item."""
        if not isinstance(item, dict):
            return item
        
        normalized = {}
        
        # Process existing fields
        for key, value in item.items():
            # Normalize key
            normalized_key = key.lower() if self.lowercase_keys else key
            
            # Apply custom field normalizer if exists
            if key in self.field_normalizers:
                normalized_value = self.field_normalizers[key](value)
            else:
                normalized_value = self._normalize_value(value, key)
            
            normalized[normalized_key] = normalized_value
        
        # Apply default values for missing fields
        for field, default_value in self.default_values.items():
            normalized_field = field.lower() if self.lowercase_keys else field
            if normalized_field not in normalized:
                normalized[normalized_field] = default_value
        
        # Apply type conversions
        for field, target_type in self.type_conversions.items():
            normalized_field = field.lower() if self.lowercase_keys else field
            if normalized_field in normalized:
                normalized[normalized_field] = self._convert_type(
                    normalized[normalized_field], target_type
                )
        
        return normalized
    
    def _normalize_value(self, value: Any, field_name: str) -> Any:
        """Normalize a single value."""
        if isinstance(value, str):
            # Strip whitespace
            if self.strip_whitespace:
                value = value.strip()
            
            # Additional string normalizations can be added here
            
        elif isinstance(value, list):
            # Recursively normalize list items
            value = [self._normalize_value(item, field_name) for item in value]
            
        elif isinstance(value, dict):
            # Recursively normalize nested dicts
            value = self._normalize_item(value)
        
        return value
    
    def _convert_type(self, value: Any, target_type: type) -> Any:
        """Convert value to target type."""
        if value is None:
            return None
        
        if isinstance(value, target_type):
            return value
        
        try:
            if target_type == bool:
                # Special handling for boolean conversion
                if isinstance(value, str):
                    return value.lower() in ('true', 'yes', '1', 'on')
                return bool(value)
                
            elif target_type == datetime:
                # Parse datetime strings
                if isinstance(value, str):
                    # Try common datetime formats
                    for fmt in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']:
                        try:
                            return datetime.strptime(value, fmt)
                        except ValueError:
                            continue
                    # If no format matches, raise error
                    raise ValueError(f"Cannot parse datetime: {value}")
                    
            else:
                # Direct type conversion
                return target_type(value)
                
        except (ValueError, TypeError) as e:
            # Log conversion error but don't fail
            context.set_metadata(
                f"{self.name}_conversion_errors",
                f"Failed to convert {value} to {target_type.__name__}: {str(e)}"
            )
            return value


class NormalizationFunctions:
    """Collection of common normalization functions."""
    
    @staticmethod
    def clean_phone_number(phone: str) -> str:
        """Remove non-numeric characters from phone number."""
        if not isinstance(phone, str):
            return str(phone)
        return re.sub(r'\D', '', phone)
    
    @staticmethod
    def normalize_email(email: str) -> str:
        """Normalize email to lowercase and strip whitespace."""
        if not isinstance(email, str):
            return email
        return email.strip().lower()
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize URL by ensuring protocol and removing trailing slash."""
        if not isinstance(url, str):
            return url
        
        url = url.strip()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url.rstrip('/')
    
    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """Replace multiple whitespace with single space."""
        if not isinstance(text, str):
            return text
        return ' '.join(text.split())
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Remove invalid characters from filename."""
        if not isinstance(filename, str):
            return filename
        # Remove invalid filename characters
        return re.sub(r'[<>:"/\\|?*]', '_', filename)


class NormalizationBuilder:
    """Builder for creating normalization stages."""
    
    def __init__(self, name: str = "normalization"):
        self.name = name
        self.description = "Normalizes data"
        self.type_conversions = {}
        self.default_values = {}
        self.field_normalizers = {}
        self.strip_whitespace = True
        self.lowercase_keys = False
    
    def convert_field(self, field: str, target_type: type) -> 'NormalizationBuilder':
        """Add type conversion for a field."""
        self.type_conversions[field] = target_type
        return self
    
    def set_default(self, field: str, default_value: Any) -> 'NormalizationBuilder':
        """Set default value for a field."""
        self.default_values[field] = default_value
        return self
    
    def normalize_field(self, field: str, normalizer: callable) -> 'NormalizationBuilder':
        """Add custom normalizer for a field."""
        self.field_normalizers[field] = normalizer
        return self
    
    def normalize_emails(self, *fields: str) -> 'NormalizationBuilder':
        """Normalize email fields."""
        for field in fields:
            self.field_normalizers[field] = NormalizationFunctions.normalize_email
        return self
    
    def normalize_phones(self, *fields: str) -> 'NormalizationBuilder':
        """Normalize phone number fields."""
        for field in fields:
            self.field_normalizers[field] = NormalizationFunctions.clean_phone_number
        return self
    
    def normalize_urls(self, *fields: str) -> 'NormalizationBuilder':
        """Normalize URL fields."""
        for field in fields:
            self.field_normalizers[field] = NormalizationFunctions.normalize_url
        return self
    
    def with_strip_whitespace(self, strip: bool) -> 'NormalizationBuilder':
        """Set whitespace stripping."""
        self.strip_whitespace = strip
        return self
    
    def with_lowercase_keys(self, lowercase: bool) -> 'NormalizationBuilder':
        """Set key lowercasing."""
        self.lowercase_keys = lowercase
        return self
    
    def build(self) -> NormalizationStage:
        """Build the normalization stage."""
        return NormalizationStage(
            name=self.name,
            description=self.description,
            type_conversions=self.type_conversions,
            default_values=self.default_values,
            field_normalizers=self.field_normalizers,
            strip_whitespace=self.strip_whitespace,
            lowercase_keys=self.lowercase_keys
        )