"""
WHERE clause validation for secure SQL-like filtering.

This module provides comprehensive validation for WHERE clause expressions
to prevent injection attacks, ReDoS, and other security vulnerabilities.
"""

import re
import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass

from .safe_evaluator import SecurityError, ExpressionValidationError

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of WHERE clause validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    normalized_clause: Optional[str] = None


class WhereClauseValidator:
    """
    Comprehensive validator for WHERE clause expressions.
    
    Provides security validation, syntax checking, and normalization
    for SQL-like WHERE clauses used in agent filtering.
    """
    
    # Maximum clause length to prevent DoS attacks
    MAX_CLAUSE_LENGTH = 2000
    
    # Maximum field path depth (e.g., a.b.c.d.e)
    MAX_FIELD_DEPTH = 8
    
    # Maximum number of conditions in a single clause
    MAX_CONDITIONS = 50
    
    # Allowed operators
    ALLOWED_OPERATORS = {
        '==', '!=', '<', '>', '<=', '>=',
        'IN', 'NOT IN', 'CONTAINS', 'NOT CONTAINS',
        'IS NULL', 'IS NOT NULL', 'LIKE', 'NOT LIKE'
    }
    
    # Allowed logical operators
    ALLOWED_LOGICAL = {'AND', 'OR', 'NOT'}
    
    # Pattern for valid field names (alphanumeric, underscore, dot notation)
    FIELD_NAME_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*$')
    
    # Patterns that could indicate injection attempts
    INJECTION_PATTERNS = [
        # SQL injection patterns
        r'(\bUNION\b|\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bDROP\b|\bALTER\b)',
        r'(\bFROM\b|\bWHERE\b|\bHAVING\b|\bGROUP\s+BY\b|\bORDER\s+BY\b)',
        r'(\bEXEC\b|\bEXECUTE\b|\bSP_\w+)',
        r'(--|/\*|\*/|xp_|sp_)',
        
        # Code injection patterns
        r'(\bimport\b|\bexec\b|\beval\b|\b__\w+__\b)',
        r'(\bopen\b|\bfile\b|\bos\.\w+|\bsys\.\w+)',
        r'(\bcompile\b|\bglobals\b|\blocals\b|\bvars\b)',
        
        # ReDoS patterns (excessive repetition)
        r'(\([^)]*\*[^)]*\){2,})',  # Nested quantifiers
        r'(\([^)]*\+[^)]*\){2,})',  # Nested plus quantifiers
        r'(\w+\*\w+\*\w+)',  # Multiple consecutive quantifiers
        
        # Path traversal
        r'(\.\./|\.\.\\|%2e%2e)',
        
        # Command injection
        r'(;\s*\w+|&&|\|\||`|\$\()',
        
        # Script injection
        r'(<script|javascript:|vbscript:|data:)',
    ]
    
    # Patterns for potentially expensive regex operations (ReDoS prevention)
    REDOS_PATTERNS = [
        r'(\(.*\*.*\).*\+)',  # Nested quantifiers with outer repetition
        r'(\(.*\+.*\).*\*)',  # Alternative nested quantifiers
        r'(.*\*.*\*.*\*)',    # Multiple consecutive stars
        r'(.*\+.*\+.*\+)',    # Multiple consecutive plus
        r'(\([^)]{20,}\)[*+])',  # Long character classes with quantifiers
    ]
    
    def __init__(self):
        """Initialize the WHERE clause validator."""
        # Compile patterns for performance
        self.injection_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.INJECTION_PATTERNS]
        self.redos_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.REDOS_PATTERNS]
    
    def validate_field_path(self, field_path: str) -> List[str]:
        """
        Validate a field path for security and syntax issues.
        
        Args:
            field_path: Field path to validate (e.g., "user.profile.email")
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        if not field_path or not isinstance(field_path, str):
            errors.append("Field path must be a non-empty string")
            return errors
        
        # Check field name pattern
        if not self.FIELD_NAME_PATTERN.match(field_path):
            errors.append(f"Invalid field path format: {field_path}")
        
        # Check depth
        depth = field_path.count('.')
        if depth > self.MAX_FIELD_DEPTH:
            errors.append(f"Field path too deep: {depth} > {self.MAX_FIELD_DEPTH}")
        
        # Check for dangerous characters
        if any(char in field_path for char in ['(', ')', '[', ']', ';', '--', '/*', '*/']):
            errors.append(f"Dangerous characters in field path: {field_path}")
        
        return errors
    
    def validate_value(self, value: str, context: str = "") -> List[str]:
        """
        Validate a value in a WHERE clause condition.
        
        Args:
            value: Value to validate
            context: Context for error messages
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        if not isinstance(value, str):
            return errors  # Non-string values are generally safe
        
        # Check for injection patterns
        for pattern in self.injection_regex:
            if pattern.search(value):
                errors.append(f"Potential injection detected in {context}: {pattern.pattern}")
        
        # Check for ReDoS patterns
        for pattern in self.redos_regex:
            if pattern.search(value):
                errors.append(f"Potential ReDoS pattern in {context}: {pattern.pattern}")
        
        return errors
    
    def parse_where_clause(self, clause: str) -> List[Dict[str, Any]]:
        """
        Parse a WHERE clause into individual conditions.
        
        Args:
            clause: WHERE clause to parse
            
        Returns:
            List of condition dictionaries
            
        Raises:
            ExpressionValidationError: If parsing fails
        """
        if not clause or not isinstance(clause, str):
            return []
        
        conditions = []
        
        # Split by AND/OR while preserving quoted strings
        parts = self._smart_split(clause, ['AND', 'OR'])
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            condition = self._parse_condition(part)
            if condition:
                conditions.append(condition)
        
        return conditions
    
    def _smart_split(self, text: str, delimiters: List[str]) -> List[str]:
        """
        Split text by delimiters while respecting quoted strings.
        
        Args:
            text: Text to split
            delimiters: List of delimiter patterns
            
        Returns:
            List of split parts
        """
        parts = []
        current_part = ""
        in_quotes = False
        quote_char = None
        i = 0
        
        while i < len(text):
            char = text[i]
            
            # Handle quotes
            if char in ['"', "'"] and (i == 0 or text[i-1] != '\\'):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif char == quote_char:
                    in_quotes = False
                    quote_char = None
            
            # Check for delimiters when not in quotes
            if not in_quotes:
                found_delimiter = None
                for delimiter in delimiters:
                    if text[i:].upper().startswith(delimiter.upper()):
                        # Check word boundaries
                        before_ok = i == 0 or not text[i-1].isalnum()
                        after_ok = i + len(delimiter) >= len(text) or not text[i + len(delimiter)].isalnum()
                        if before_ok and after_ok:
                            found_delimiter = delimiter
                            break
                
                if found_delimiter:
                    if current_part.strip():
                        parts.append(current_part.strip())
                    current_part = ""
                    i += len(found_delimiter)
                    continue
            
            current_part += char
            i += 1
        
        if current_part.strip():
            parts.append(current_part.strip())
        
        return parts
    
    def _parse_condition(self, condition_str: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single condition string.
        
        Args:
            condition_str: Condition string to parse
            
        Returns:
            Condition dictionary or None if parsing fails
        """
        condition_str = condition_str.strip()
        
        # Handle NULL checks first
        for null_op in ['IS NOT NULL', 'IS NULL']:
            if null_op in condition_str.upper():
                field = condition_str.upper().replace(null_op, '').strip()
                return {
                    'field': field,
                    'operator': null_op,
                    'value': None,
                    'type': 'null_check'
                }
        
        # Handle other operators
        for operator in sorted(self.ALLOWED_OPERATORS, key=len, reverse=True):
            if operator in condition_str.upper():
                # Split on the operator
                parts = condition_str.upper().split(operator.upper())
                if len(parts) == 2:
                    field = parts[0].strip()
                    value_str = parts[1].strip()
                    
                    # Parse the value
                    value = self._parse_value(value_str)
                    
                    return {
                        'field': field,
                        'operator': operator,
                        'value': value,
                        'type': 'comparison'
                    }
        
        return None
    
    def _parse_value(self, value_str: str) -> Any:
        """
        Parse a value string into appropriate Python type.
        
        Args:
            value_str: Value string to parse
            
        Returns:
            Parsed value
        """
        value_str = value_str.strip()
        
        # Handle quoted strings
        if ((value_str.startswith('"') and value_str.endswith('"')) or
            (value_str.startswith("'") and value_str.endswith("'"))):
            return value_str[1:-1]
        
        # Handle boolean values
        if value_str.upper() == 'TRUE':
            return True
        if value_str.upper() == 'FALSE':
            return False
        
        # Handle null
        if value_str.upper() == 'NULL':
            return None
        
        # Handle numbers
        try:
            if '.' in value_str:
                return float(value_str)
            else:
                return int(value_str)
        except ValueError:
            pass
        
        # Handle arrays (simplified)
        if value_str.startswith('[') and value_str.endswith(']'):
            try:
                # Basic array parsing - more secure than eval
                content = value_str[1:-1].strip()
                if not content:
                    return []
                
                items = []
                parts = content.split(',')
                for part in parts:
                    part = part.strip()
                    if ((part.startswith('"') and part.endswith('"')) or
                        (part.startswith("'") and part.endswith("'"))):
                        items.append(part[1:-1])
                    else:
                        try:
                            if '.' in part:
                                items.append(float(part))
                            else:
                                items.append(int(part))
                        except ValueError:
                            items.append(part)
                return items
            except Exception:
                pass
        
        # Return as string if all else fails
        return value_str
    
    def validate_clause(self, clause: str, allowed_fields: Optional[Set[str]] = None) -> ValidationResult:
        """
        Comprehensively validate a WHERE clause.
        
        Args:
            clause: WHERE clause to validate
            allowed_fields: Set of allowed field names (optional)
            
        Returns:
            ValidationResult with validation status and details
        """
        errors = []
        warnings = []
        
        # Basic checks
        if not clause or not isinstance(clause, str):
            errors.append("WHERE clause must be a non-empty string")
            return ValidationResult(False, errors, warnings)
        
        # Length check
        if len(clause) > self.MAX_CLAUSE_LENGTH:
            errors.append(f"WHERE clause too long: {len(clause)} > {self.MAX_CLAUSE_LENGTH}")
        
        # Injection pattern checks
        for pattern in self.injection_regex:
            if pattern.search(clause):
                errors.append(f"Potential injection pattern detected: {pattern.pattern}")
        
        # ReDoS pattern checks
        for pattern in self.redos_regex:
            if pattern.search(clause):
                errors.append(f"Potential ReDoS pattern detected: {pattern.pattern}")
        
        # Parse and validate conditions
        try:
            conditions = self.parse_where_clause(clause)
            
            if len(conditions) > self.MAX_CONDITIONS:
                errors.append(f"Too many conditions: {len(conditions)} > {self.MAX_CONDITIONS}")
            
            for i, condition in enumerate(conditions):
                # Validate field path
                field = condition.get('field', '')
                field_errors = self.validate_field_path(field)
                for error in field_errors:
                    errors.append(f"Condition {i+1}: {error}")
                
                # Check if field is allowed
                if allowed_fields and field not in allowed_fields:
                    warnings.append(f"Field '{field}' not in allowed fields list")
                
                # Validate operator
                operator = condition.get('operator', '')
                if operator not in self.ALLOWED_OPERATORS:
                    errors.append(f"Condition {i+1}: Invalid operator '{operator}'")
                
                # Validate value
                value = condition.get('value')
                if isinstance(value, str):
                    value_errors = self.validate_value(value, f"condition {i+1} value")
                    errors.extend(value_errors)
                
        except Exception as e:
            errors.append(f"Failed to parse WHERE clause: {e}")
        
        # Check for balanced parentheses
        if clause.count('(') != clause.count(')'):
            errors.append("Unbalanced parentheses in WHERE clause")
        
        # Check for balanced quotes
        single_quotes = clause.count("'") - clause.count("\\'")
        double_quotes = clause.count('"') - clause.count('\\"')
        if single_quotes % 2 != 0:
            errors.append("Unbalanced single quotes in WHERE clause")
        if double_quotes % 2 != 0:
            errors.append("Unbalanced double quotes in WHERE clause")
        
        is_valid = len(errors) == 0
        normalized_clause = self._normalize_clause(clause) if is_valid else None
        
        return ValidationResult(is_valid, errors, warnings, normalized_clause)
    
    def _normalize_clause(self, clause: str) -> str:
        """
        Normalize a WHERE clause for consistent processing.
        
        Args:
            clause: WHERE clause to normalize
            
        Returns:
            Normalized clause
        """
        # Basic normalization - can be extended
        normalized = clause.strip()
        
        # Normalize operators to uppercase
        for op in self.ALLOWED_OPERATORS:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(op.lower()) + r'\b'
            normalized = re.sub(pattern, op, normalized, flags=re.IGNORECASE)
        
        # Normalize logical operators
        for logical_op in self.ALLOWED_LOGICAL:
            pattern = r'\b' + re.escape(logical_op.lower()) + r'\b'
            normalized = re.sub(pattern, logical_op, normalized, flags=re.IGNORECASE)
        
        return normalized
    
    def get_referenced_fields(self, clause: str) -> Set[str]:
        """
        Extract all field names referenced in a WHERE clause.
        
        Args:
            clause: WHERE clause to analyze
            
        Returns:
            Set of field names
        """
        fields = set()
        
        try:
            conditions = self.parse_where_clause(clause)
            for condition in conditions:
                field = condition.get('field', '')
                if field:
                    fields.add(field)
        except Exception:
            # If parsing fails, try regex extraction as fallback
            field_matches = self.FIELD_NAME_PATTERN.findall(clause)
            for match in field_matches:
                fields.add(match)
        
        return fields


# Global instance for convenient access
where_clause_validator = WhereClauseValidator()


def validate_where_clause(clause: str, allowed_fields: Optional[Set[str]] = None) -> ValidationResult:
    """
    Convenience function for WHERE clause validation.
    
    Args:
        clause: WHERE clause to validate
        allowed_fields: Set of allowed field names (optional)
        
    Returns:
        ValidationResult with validation status and details
    """
    return where_clause_validator.validate_clause(clause, allowed_fields)


def is_safe_where_clause(clause: str) -> bool:
    """
    Quick check if a WHERE clause is safe.
    
    Args:
        clause: WHERE clause to check
        
    Returns:
        True if clause appears safe, False otherwise
    """
    result = where_clause_validator.validate_clause(clause)
    return result.is_valid


def get_where_clause_fields(clause: str) -> Set[str]:
    """
    Extract field names from a WHERE clause.
    
    Args:
        clause: WHERE clause to analyze
        
    Returns:
        Set of field names
    """
    return where_clause_validator.get_referenced_fields(clause)