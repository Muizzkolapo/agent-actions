"""
Production-grade secure WHERE clause parser.
Replaces unsafe eval() with AST-based evaluation and comprehensive security checks.
"""
import re
import ast
import time
import threading
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import logging

from agent_actions._internal.common.monitoring.metrics import (
    get_metrics_collector, record_where_clause_evaluation, 
    record_where_clause_cache_hit, record_where_clause_cache_miss,
    record_where_clause_error
)
from agent_actions._internal.common.monitoring.logging import (
    get_logger, log_where_clause_start, log_where_clause_success,
    log_where_clause_error, log_security_violation
)
from agent_actions._internal.common.resilience.circuit_breaker import circuit_breaker
from agent_actions._internal.common.resilience.retry import where_clause_retry
from agent_actions._internal.common.feature_flags.manager import (
    where_clause_enabled, where_clause_caching_enabled,
    where_clause_debug_enabled, where_clause_security_enabled
)

logger = logging.getLogger(__name__)


class SecurityViolationError(Exception):
    """Exception raised when security violations are detected."""
    pass


class InvalidWhereClauseError(Exception):
    """Exception raised for invalid WHERE clause syntax."""
    pass


class WhereClauseTimeoutError(Exception):
    """Exception raised when WHERE clause evaluation times out."""
    pass


@dataclass
class WhereCondition:
    """Represents a single WHERE condition."""
    field: str
    operator: str
    value: Any
    negated: bool = False


@dataclass
class SecurityContext:
    """Security context for WHERE clause evaluation."""
    allowed_fields: Set[str]
    max_clause_length: int = 1000
    max_conditions: int = 10
    max_evaluation_time_ms: float = 100.0
    allow_nested_fields: bool = True
    max_nesting_depth: int = 5


class OperatorType(Enum):
    """Supported operator types."""
    EQUALITY = "equality"
    COMPARISON = "comparison" 
    CONTAINMENT = "containment"
    EXISTENCE = "existence"
    ARRAY = "array"


class SecureWhereClauseParser:
    """
    Production-grade secure WHERE clause parser.
    Uses AST parsing instead of eval() for security.
    """
    
    # Allowed operators with their Python equivalents
    OPERATORS = {
        # Equality operators
        '==': ('eq', OperatorType.EQUALITY),
        '=': ('eq', OperatorType.EQUALITY),  # SQL compatibility
        '!=': ('ne', OperatorType.EQUALITY),
        '<>': ('ne', OperatorType.EQUALITY),  # SQL compatibility
        
        # Comparison operators
        '>': ('gt', OperatorType.COMPARISON),
        '>=': ('gte', OperatorType.COMPARISON),
        '<': ('lt', OperatorType.COMPARISON),
        '<=': ('lte', OperatorType.COMPARISON),
        
        # Containment operators
        'IN': ('in', OperatorType.ARRAY),
        'NOT IN': ('not_in', OperatorType.ARRAY),
        'CONTAINS': ('contains', OperatorType.CONTAINMENT),
        'NOT CONTAINS': ('not_contains', OperatorType.CONTAINMENT),
        'LIKE': ('like', OperatorType.CONTAINMENT),
        'NOT LIKE': ('not_like', OperatorType.CONTAINMENT),
        
        # Existence operators
        'IS NULL': ('is_null', OperatorType.EXISTENCE),
        'IS NOT NULL': ('is_not_null', OperatorType.EXISTENCE),
    }
    
    # Security patterns to detect potential attacks
    SECURITY_PATTERNS = [
        (r'__\w+__', "dunder_access"),  # Python dunder methods
        (r'\beval\b', "eval_injection"),
        (r'\bexec\b', "exec_injection"),
        (r'\b__import__\b', "import_injection"),
        (r'\bgetattr\b', "getattr_access"),
        (r'\bsetattr\b', "setattr_access"),
        (r'\bdelattr\b', "delattr_access"),
        (r'\bdir\b', "dir_introspection"),
        (r'\bglobals\b', "globals_access"),
        (r'\blocals\b', "locals_access"),
        (r'\bvars\b', "vars_access"),
        (r'<script[^>]*>', "script_injection"),
        (r'javascript:', "javascript_protocol"),
        (r'[\x00-\x1f\x7f-\x9f]', "control_characters"),
    ]
    
    def __init__(self, security_context: Optional[SecurityContext] = None):
        self.security_context = security_context or SecurityContext(
            allowed_fields=set(),  # Empty means all fields allowed
            max_clause_length=1000,
            max_conditions=10,
            max_evaluation_time_ms=100.0
        )
        
        self.metrics = get_metrics_collector()
        self.structured_logger = get_logger()
        
        # Caching
        self._parse_cache = {}
        self._cache_lock = threading.RLock()
        self._cache_stats = {'hits': 0, 'misses': 0}
    
    def _validate_security(self, clause: str, agent_type: str) -> None:
        """Perform comprehensive security validation."""
        if not where_clause_security_enabled(agent_type):
            return
        
        # Check clause length
        if len(clause) > self.security_context.max_clause_length:
            violation = {
                'clause_length': len(clause),
                'max_length': self.security_context.max_clause_length,
                'clause_preview': clause[:100] + '...' if len(clause) > 100 else clause
            }
            log_security_violation("clause_too_long", "high", violation)
            raise SecurityViolationError(f"WHERE clause too long: {len(clause)} > {self.security_context.max_clause_length}")
        
        # Check for security patterns
        for pattern, violation_type in self.SECURITY_PATTERNS:
            if re.search(pattern, clause, re.IGNORECASE):
                violation = {
                    'pattern': pattern,
                    'violation_type': violation_type,
                    'clause': clause
                }
                log_security_violation(violation_type, "critical", violation)
                raise SecurityViolationError(f"Security violation detected: {violation_type}")
        
        # Check for suspicious repeated patterns (ReDoS protection)
        if self._detect_redos_patterns(clause):
            log_security_violation("potential_redos", "high", {'clause': clause})
            raise SecurityViolationError("Potential ReDoS attack detected")
    
    def _detect_redos_patterns(self, clause: str) -> bool:
        """Detect potential ReDoS (Regular Expression Denial of Service) patterns."""
        # Look for patterns that could cause exponential backtracking
        redos_patterns = [
            r'(.+)+',  # Nested quantifiers
            r'(.*).*',  # Overlapping quantifiers
            r'(a+)+',   # Nested repeating groups
            r'(a|a)*',  # Alternation with overlap
        ]
        
        for pattern in redos_patterns:
            try:
                if re.search(pattern, clause):
                    return True
            except re.error:
                # If regex compilation fails, it's suspicious
                return True
        
        # Check for excessive repetition of characters that could indicate attack
        for char in ".*+?{}[]()|\\":
            if clause.count(char) > 20:  # Arbitrary threshold
                return True
        
        return False
    
    def _validate_field_access(self, field_path: str) -> None:
        """Validate field access permissions."""
        # Check if field is in allowed list (if specified)
        if self.security_context.allowed_fields:
            root_field = field_path.split('.')[0]
            if root_field not in self.security_context.allowed_fields:
                raise SecurityViolationError(f"Field access denied: {field_path}")
        
        # Check nesting depth
        if not self.security_context.allow_nested_fields and '.' in field_path:
            raise SecurityViolationError(f"Nested field access not allowed: {field_path}")
        
        nesting_depth = field_path.count('.')
        if nesting_depth > self.security_context.max_nesting_depth:
            raise SecurityViolationError(
                f"Field nesting too deep: {nesting_depth} > {self.security_context.max_nesting_depth}"
            )
        
        # Validate field name format
        for part in field_path.split('.'):
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', part):
                raise SecurityViolationError(f"Invalid field name format: {part}")
    
    @lru_cache(maxsize=1000)
    def _parse_value_cached(self, value_str: str) -> Any:
        """Parse value string with caching."""
        return self._parse_value_uncached(value_str)
    
    def _parse_value_uncached(self, value_str: str) -> Any:
        """Parse value string into appropriate Python type."""
        value_str = value_str.strip()
        
        # Handle quoted strings
        if ((value_str.startswith('"') and value_str.endswith('"')) or
            (value_str.startswith("'") and value_str.endswith("'"))):
            return value_str[1:-1]
        
        # Handle boolean values
        if value_str.lower() == 'true':
            return True
        if value_str.lower() == 'false':
            return False
        
        # Handle null values
        if value_str.lower() in ('null', 'none'):
            return None
        
        # Handle numeric values
        try:
            if '.' in value_str:
                return float(value_str)
            else:
                return int(value_str)
        except ValueError:
            pass
        
        # Handle arrays using AST parsing (secure)
        if value_str.startswith('[') and value_str.endswith(']'):
            try:
                # Use AST to safely parse array literals
                node = ast.parse(value_str, mode='eval')
                if isinstance(node.body, ast.List):
                    result = []
                    for elt in node.body.elts:
                        if isinstance(elt, ast.Constant):
                            result.append(elt.value)
                        elif isinstance(elt, ast.Str):  # Python < 3.8 compatibility
                            result.append(elt.s)
                        elif isinstance(elt, ast.Num):  # Python < 3.8 compatibility
                            result.append(elt.n)
                        else:
                            raise ValueError("Unsupported array element type")
                    return result
            except (SyntaxError, ValueError) as e:
                raise InvalidWhereClauseError(f"Invalid array syntax: {value_str}")
        
        # Return as string if nothing else matches
        return value_str
    
    def _get_cache_key(self, clause: str) -> str:
        """Generate cache key for parsed clause."""
        return f"parse:{hash(clause)}"
    
    def parse(self, clause: str, agent_type: str = "unknown") -> List[WhereCondition]:
        """
        Parse WHERE clause into structured conditions.
        
        Args:
            clause: WHERE clause string
            agent_type: Agent type for security context
            
        Returns:
            List of WhereCondition objects
            
        Raises:
            SecurityViolationError: For security violations
            InvalidWhereClauseError: For invalid syntax
        """
        start_time = time.time()
        
        # Check if WHERE clause functionality is enabled
        if not where_clause_enabled(agent_type):
            raise InvalidWhereClauseError("WHERE clause functionality is disabled")
        
        # Security validation
        self._validate_security(clause, agent_type)
        
        # Check cache first
        cache_key = self._get_cache_key(clause)
        use_cache = where_clause_caching_enabled(agent_type)
        
        if use_cache:
            with self._cache_lock:
                if cache_key in self._parse_cache:
                    self._cache_stats['hits'] += 1
                    record_where_clause_cache_hit("parse")
                    return self._parse_cache[cache_key].copy()
                else:
                    self._cache_stats['misses'] += 1
                    record_where_clause_cache_miss("parse")
        
        try:
            # Parse the clause
            conditions = self._parse_clause(clause)
            
            # Validate condition count
            if len(conditions) > self.security_context.max_conditions:
                raise SecurityViolationError(
                    f"Too many conditions: {len(conditions)} > {self.security_context.max_conditions}"
                )
            
            # Cache the result
            if use_cache:
                with self._cache_lock:
                    self._parse_cache[cache_key] = conditions.copy()
            
            # Record success metrics
            evaluation_time = (time.time() - start_time) * 1000
            record_where_clause_evaluation("parse", agent_type, "success", evaluation_time)
            
            # Log success
            if where_clause_debug_enabled(agent_type):
                log_where_clause_success(
                    clause, "parse", evaluation_time, len(conditions), 0, 0
                )
            
            return conditions
        
        except Exception as e:
            evaluation_time = (time.time() - start_time) * 1000
            record_where_clause_error(type(e).__name__, agent_type, "parse")
            
            # Log error
            log_where_clause_error(
                clause, "parse", evaluation_time, 0, e, 
                {'agent_type': agent_type}
            )
            
            raise
    
    def _parse_clause(self, clause: str) -> List[WhereCondition]:
        """Parse the WHERE clause string."""
        clause = clause.strip()
        if not clause:
            return []
        
        conditions = []
        
        # Split by AND (we can extend to support OR later)
        and_parts = self._split_by_and(clause)
        
        for part in and_parts:
            condition = self._parse_single_condition(part.strip())
            if condition:
                conditions.append(condition)
        
        return conditions
    
    def _split_by_and(self, clause: str) -> List[str]:
        """Split clause by AND operators, respecting quotes and parentheses."""
        parts = []
        current_part = ""
        in_quotes = False
        quote_char = None
        paren_depth = 0
        i = 0
        
        while i < len(clause):
            char = clause[i]
            
            # Handle quotes
            if char in ('"', "'") and not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char and in_quotes:
                in_quotes = False
                quote_char = None
            
            # Handle parentheses (for future OR support)
            elif not in_quotes:
                if char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth -= 1
                
                # Check for AND
                elif (paren_depth == 0 and 
                      clause[i:i+4].upper() == ' AND' and 
                      (i + 4 >= len(clause) or clause[i+4] == ' ')):
                    parts.append(current_part)
                    current_part = ""
                    i += 4  # Skip " AND"
                    continue
            
            current_part += char
            i += 1
        
        if current_part.strip():
            parts.append(current_part)
        
        return parts
    
    def _parse_single_condition(self, condition_str: str) -> Optional[WhereCondition]:
        """Parse a single condition string."""
        condition_str = condition_str.strip()
        
        # Handle NULL checks first (they have special syntax)
        for null_op in ['IS NOT NULL', 'IS NULL']:
            if null_op in condition_str.upper():
                field = condition_str.upper().replace(null_op, '').strip()
                self._validate_field_access(field)
                return WhereCondition(
                    field=field.lower(),
                    operator=null_op,
                    value=None
                )
        
        # Find the operator
        for op_str, (op_func, op_type) in self.OPERATORS.items():
            if op_str.upper() in condition_str.upper():
                # Split on the operator
                parts = re.split(
                    f'\\s*{re.escape(op_str)}\\s*',
                    condition_str,
                    flags=re.IGNORECASE,
                    maxsplit=1
                )
                
                if len(parts) == 2:
                    field = parts[0].strip()
                    value_str = parts[1].strip()
                    
                    # Validate field access
                    self._validate_field_access(field)
                    
                    # Parse value
                    value = self._parse_value_cached(value_str)
                    
                    return WhereCondition(
                        field=field,
                        operator=op_str.upper(),
                        value=value
                    )
        
        # If no operator found, it's invalid
        raise InvalidWhereClauseError(f"No valid operator found in condition: {condition_str}")
    
    @circuit_breaker(
        failure_threshold=3,
        recovery_timeout=30.0,
        timeout=1.0,  # 1 second timeout for WHERE clause evaluation
        name="where_clause_evaluation"
    )
    @where_clause_retry("unknown", "evaluation", max_attempts=2)
    def evaluate(
        self,
        data: Dict[str, Any],
        conditions: List[WhereCondition],
        agent_type: str = "unknown"
    ) -> bool:
        """
        Evaluate conditions against data with comprehensive monitoring.
        
        Args:
            data: Data to evaluate against
            conditions: List of conditions to evaluate
            agent_type: Agent type for context
            
        Returns:
            True if all conditions match, False otherwise
        """
        start_time = time.time()
        
        try:
            # Check timeout
            max_time = self.security_context.max_evaluation_time_ms / 1000.0
            
            log_where_clause_start("evaluation", "item", len(conditions), 1)
            
            for condition in conditions:
                # Check timeout during evaluation
                elapsed = time.time() - start_time
                if elapsed > max_time:
                    raise WhereClauseTimeoutError(
                        f"WHERE clause evaluation timeout: {elapsed:.3f}s > {max_time:.3f}s"
                    )
                
                if not self._evaluate_condition(condition, data):
                    # Record filtered result
                    record_where_clause_filter_result(agent_type, "filtered", 1)
                    return False
            
            # All conditions passed
            evaluation_time = (time.time() - start_time) * 1000
            
            # Record success
            record_where_clause_filter_result(agent_type, "passed", 1)
            record_where_clause_evaluation("item", agent_type, "success", evaluation_time)
            
            if where_clause_debug_enabled(agent_type):
                log_where_clause_success(
                    "evaluation", "item", evaluation_time, len(conditions), 1, 1
                )
            
            return True
        
        except Exception as e:
            evaluation_time = (time.time() - start_time) * 1000
            record_where_clause_error(type(e).__name__, agent_type, "item")
            
            log_where_clause_error(
                "evaluation", "item", evaluation_time, len(conditions), e,
                {'agent_type': agent_type, 'data_keys': list(data.keys()) if data else []}
            )
            
            # Re-raise the exception
            raise
    
    def _evaluate_condition(self, condition: WhereCondition, data: Dict[str, Any]) -> bool:
        """Evaluate a single condition against data."""
        field_value = self._get_nested_value(data, condition.field)
        
        # Handle different operators
        if condition.operator == '==' or condition.operator == '=':
            result = field_value == condition.value
        elif condition.operator == '!=' or condition.operator == '<>':
            result = field_value != condition.value
        elif condition.operator == '>':
            result = self._safe_compare(field_value, condition.value, lambda a, b: a > b)
        elif condition.operator == '>=':
            result = self._safe_compare(field_value, condition.value, lambda a, b: a >= b)
        elif condition.operator == '<':
            result = self._safe_compare(field_value, condition.value, lambda a, b: a < b)
        elif condition.operator == '<=':
            result = self._safe_compare(field_value, condition.value, lambda a, b: a <= b)
        elif condition.operator == 'IN':
            result = self._safe_in_check(field_value, condition.value, True)
        elif condition.operator == 'NOT IN':
            result = self._safe_in_check(field_value, condition.value, False)
        elif condition.operator == 'CONTAINS':
            result = self._safe_contains_check(field_value, condition.value, True)
        elif condition.operator == 'NOT CONTAINS':
            result = self._safe_contains_check(field_value, condition.value, False)
        elif condition.operator == 'IS NULL':
            result = field_value is None
        elif condition.operator == 'IS NOT NULL':
            result = field_value is not None
        elif condition.operator == 'LIKE':
            result = self._safe_like_check(field_value, condition.value, True)
        elif condition.operator == 'NOT LIKE':
            result = self._safe_like_check(field_value, condition.value, False)
        else:
            raise InvalidWhereClauseError(f"Unsupported operator: {condition.operator}")
        
        return result
    
    def _get_nested_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Get value from nested dictionary using dot notation."""
        if not isinstance(data, dict):
            return None
        
        keys = field_path.split('.')
        value = data
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        
        return value
    
    def _safe_compare(self, a: Any, b: Any, comparator) -> bool:
        """Safely compare values with type checking."""
        if a is None or b is None:
            return False
        
        try:
            # Ensure compatible types
            if type(a) != type(b):
                # Try to convert to common type
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    return comparator(a, b)
                else:
                    # Convert both to strings for comparison
                    return comparator(str(a), str(b))
            return comparator(a, b)
        except (TypeError, ValueError):
            return False
    
    def _safe_in_check(self, value: Any, container: Any, positive: bool) -> bool:
        """Safely check if value is in container."""
        if container is None or not isinstance(container, (list, tuple, set)):
            return not positive  # If container is invalid, return opposite of expected
        
        try:
            result = value in container
            return result if positive else not result
        except (TypeError, ValueError):
            return not positive
    
    def _safe_contains_check(self, haystack: Any, needle: Any, positive: bool) -> bool:
        """Safely check if haystack contains needle."""
        if haystack is None:
            return not positive
        
        try:
            haystack_str = str(haystack)
            needle_str = str(needle)
            result = needle_str in haystack_str
            return result if positive else not result
        except (TypeError, ValueError):
            return not positive
    
    def _safe_like_check(self, value: Any, pattern: Any, positive: bool) -> bool:
        """Safely check LIKE pattern matching."""
        if value is None or pattern is None:
            return not positive
        
        try:
            # Convert SQL LIKE pattern to regex
            regex_pattern = str(pattern).replace('%', '.*').replace('_', '.')
            result = bool(re.search(f'^{regex_pattern}$', str(value), re.IGNORECASE))
            return result if positive else not result
        except (TypeError, ValueError, re.error):
            return not positive
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._cache_lock:
            total = self._cache_stats['hits'] + self._cache_stats['misses']
            hit_rate = self._cache_stats['hits'] / total if total > 0 else 0.0
            
            return {
                'hits': self._cache_stats['hits'],
                'misses': self._cache_stats['misses'],
                'hit_rate': hit_rate,
                'cache_size': len(self._parse_cache)
            }
    
    def clear_cache(self):
        """Clear the parse cache."""
        with self._cache_lock:
            self._parse_cache.clear()
            self._cache_stats = {'hits': 0, 'misses': 0}


# Global secure parser instance
_secure_parser: Optional[SecureWhereClauseParser] = None
_parser_lock = threading.Lock()


def get_secure_parser(security_context: Optional[SecurityContext] = None) -> SecureWhereClauseParser:
    """Get or create the global secure parser."""
    global _secure_parser
    
    if _secure_parser is None:
        with _parser_lock:
            if _secure_parser is None:
                _secure_parser = SecureWhereClauseParser(security_context)
    
    return _secure_parser


def init_secure_parser(security_context: Optional[SecurityContext] = None) -> SecureWhereClauseParser:
    """Initialize the global secure parser."""
    global _secure_parser
    
    with _parser_lock:
        _secure_parser = SecureWhereClauseParser(security_context)
    
    return _secure_parser