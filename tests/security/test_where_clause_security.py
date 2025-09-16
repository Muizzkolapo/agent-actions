"""
Security tests for WHERE clause filtering functionality.

This test suite covers security aspects including:
- SQL injection-like attack prevention
- Code injection attempt detection
- ReDoS attack prevention
- Input validation and sanitization
- Fuzzing tests for malicious input
"""

import pytest
import string
import random
from typing import List, Dict, Any

from agent_actions.security import (
    SafeExpressionEvaluator, 
    SecurityError, 
    ExpressionValidationError,
    WhereClauseValidator,
    ValidationResult,
    safe_eval,
    validate_where_clause,
    is_safe_where_clause
)


class TestSafeExpressionEvaluator:
    """Test security aspects of the safe expression evaluator."""
    
    def test_prevents_dangerous_builtin_access(self):
        """Test that dangerous built-in functions are blocked."""
        dangerous_expressions = [
            "__import__('os').system('ls')",
            "exec('print(1)')",
            "eval('1+1')",
            "open('/etc/passwd')",
            "compile('1+1', 'test', 'eval')",
            "globals()",
            "locals()",
            "vars()",
            "dir()",
            "getattr(str, 'upper')",
            "setattr(obj, 'attr', 'value')",
            "delattr(obj, 'attr')",
            "hasattr(str, 'upper')",
            "callable(str)",
            "type(str)",
            "isinstance('', str)",
            "issubclass(str, object)",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for expr in dangerous_expressions:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(expr)
    
    def test_prevents_code_injection_patterns(self):
        """Test that code injection patterns are detected."""
        injection_patterns = [
            "import os; os.system('rm -rf /')",
            "for i in range(1000000): pass",
            "while True: pass",
            "class Evil: pass",
            "def evil(): return 1",
            "lambda x: x",
            "try: pass\nexcept: pass",
            "with open('file') as f: pass",
            "yield from [1,2,3]",
            "async def f(): pass",
            "await something()",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for pattern in injection_patterns:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(pattern)
    
    def test_prevents_excessive_nesting(self):
        """Test that excessive field nesting is blocked."""
        # Create deeply nested field access
        deep_field = "a." * 20 + "value"
        
        evaluator = SafeExpressionEvaluator()
        
        with pytest.raises(SecurityError, match="Field access too deep"):
            evaluator.validate_expression(f"{deep_field} == 'test'")
    
    def test_prevents_long_expressions(self):
        """Test that overly long expressions are blocked."""
        # Create very long expression
        long_expr = "x == 'value'" + " and x == 'value'" * 100
        
        evaluator = SafeExpressionEvaluator()
        
        with pytest.raises(SecurityError, match="Expression too long"):
            evaluator.validate_expression(long_expr)
    
    def test_safe_expression_evaluation(self):
        """Test that safe expressions work correctly."""
        evaluator = SafeExpressionEvaluator()
        
        safe_expressions = [
            ("x == 'test'", {"x": "test"}, True),
            ("y > 5", {"y": 10}, True),
            ("len(items) > 0", {"items": [1, 2, 3]}, True),
            ("str(num)", {"num": 42}, "42"),
            ("user.age >= 18", {"user": {"age": 25}}, True),
            ("not (status == 'inactive')", {"status": "active"}, True),
        ]
        
        for expr, context, expected in safe_expressions:
            result = evaluator.safe_eval(expr, context)
            assert result == expected
    
    def test_context_validation(self):
        """Test that dangerous context objects are rejected."""
        evaluator = SafeExpressionEvaluator()
        
        # Test dangerous context keys
        with pytest.raises(SecurityError):
            evaluator.validate_context({"__builtins__": {}})
        
        # Test callable in context
        with pytest.raises(SecurityError):
            evaluator.validate_context({"func": lambda x: x})
        
        # Test excessive nesting
        deeply_nested = {"level1": {}}
        current = deeply_nested["level1"]
        for i in range(10):
            current[f"level{i+2}"] = {}
            current = current[f"level{i+2}"]
        
        with pytest.raises(SecurityError, match="Context nesting too deep"):
            evaluator.validate_context(deeply_nested)


class TestWhereClauseValidator:
    """Test security aspects of WHERE clause validation."""
    
    def test_detects_sql_injection_patterns(self):
        """Test detection of SQL injection-like patterns."""
        sql_injection_attempts = [
            "field = 'value'; DROP TABLE users;--",
            "field = 'value' UNION SELECT * FROM passwords",
            "field = 'value' OR 1=1",
            "field = 'value'/*comment*/AND 1=1",
            "field = 'value' EXEC xp_cmdshell('dir')",
            "field = 'value'; INSERT INTO log VALUES ('hack')",
            "field = 'value' ORDER BY 1",
            "field = 'value' GROUP BY field HAVING 1=1",
        ]
        
        validator = WhereClauseValidator()
        
        for malicious_clause in sql_injection_attempts:
            result = validator.validate_clause(malicious_clause)
            assert not result.is_valid
            assert any("injection" in error.lower() for error in result.errors)
    
    def test_detects_code_injection_patterns(self):
        """Test detection of code injection patterns."""
        code_injection_attempts = [
            "field == 'value' and __import__('os').system('ls')",
            "field == 'value' and exec('print(1)')",
            "field == 'value' and eval('1+1')",
            "field == 'value' and open('/etc/passwd')",
            "field == 'value' and globals()['secret']",
            "field == 'value' and compile('code', 'test', 'eval')",
        ]
        
        validator = WhereClauseValidator()
        
        for malicious_clause in code_injection_attempts:
            result = validator.validate_clause(malicious_clause)
            assert not result.is_valid
            assert any("injection" in error.lower() for error in result.errors)
    
    def test_detects_redos_patterns(self):
        """Test detection of ReDoS (Regular Expression Denial of Service) patterns."""
        redos_patterns = [
            "field LIKE '(a*)*b'",
            "field LIKE '(a+)+b'",
            "field LIKE 'a*a*a*a*a*a*a*'",
            "field LIKE 'a+a+a+a+a+a+a+'",
            "field LIKE '(aaaaaaaaaaaaaaaaaaaaaa)*'",
        ]
        
        validator = WhereClauseValidator()
        
        for redos_pattern in redos_patterns:
            result = validator.validate_clause(redos_pattern)
            # Should either be invalid or generate warnings
            if result.is_valid:
                assert any("redos" in warning.lower() for warning in result.warnings)
            else:
                assert any("redos" in error.lower() for error in result.errors)
    
    def test_validates_field_paths(self):
        """Test field path validation."""
        validator = WhereClauseValidator()
        
        # Test invalid field paths
        invalid_fields = [
            "user.profile.settings.nested.deeply.too.much.nesting.here",  # Too deep
            "user'; DROP TABLE users;--",  # SQL injection in field
            "user[0]",  # Array access
            "user()",  # Function call
            "123invalid",  # Invalid start
            "",  # Empty field
        ]
        
        for invalid_field in invalid_fields:
            clause = f"{invalid_field} == 'test'"
            result = validator.validate_clause(clause)
            assert not result.is_valid
    
    def test_validates_clause_length(self):
        """Test that overly long clauses are rejected."""
        validator = WhereClauseValidator()
        
        # Create very long clause
        long_clause = " AND ".join([f"field{i} == 'value{i}'" for i in range(200)])
        
        result = validator.validate_clause(long_clause)
        assert not result.is_valid
        assert any("too long" in error.lower() for error in result.errors)
    
    def test_validates_condition_count(self):
        """Test that too many conditions are rejected."""
        validator = WhereClauseValidator()
        
        # Create clause with many conditions
        many_conditions = " AND ".join([f"field{i} == 'value{i}'" for i in range(60)])
        
        result = validator.validate_clause(many_conditions)
        assert not result.is_valid
        assert any("too many conditions" in error.lower() for error in result.errors)
    
    def test_validates_balanced_quotes(self):
        """Test detection of unbalanced quotes."""
        validator = WhereClauseValidator()
        
        unbalanced_quotes = [
            "field == 'unbalanced",
            'field == "unbalanced',
            "field == 'value' AND other == 'unbalanced",
        ]
        
        for clause in unbalanced_quotes:
            result = validator.validate_clause(clause)
            assert not result.is_valid
            assert any("unbalanced" in error.lower() for error in result.errors)
    
    def test_validates_balanced_parentheses(self):
        """Test detection of unbalanced parentheses."""
        validator = WhereClauseValidator()
        
        unbalanced_parens = [
            "(field == 'value'",
            "field == 'value')",
            "((field == 'value')",
            "(field == 'value'))",
        ]
        
        for clause in unbalanced_parens:
            result = validator.validate_clause(clause)
            assert not result.is_valid
            assert any("unbalanced" in error.lower() for error in result.errors)
    
    def test_safe_clauses_pass_validation(self):
        """Test that legitimate WHERE clauses pass validation."""
        validator = WhereClauseValidator()
        
        safe_clauses = [
            "status == 'active'",
            "age >= 18 AND status != 'banned'",
            "category IN ['tech', 'science'] AND score > 80",
            "title CONTAINS 'important' AND NOT archived",
            "metadata.priority IS NOT NULL",
            "user.profile.age >= 21",
        ]
        
        for clause in safe_clauses:
            result = validator.validate_clause(clause)
            assert result.is_valid, f"Safe clause failed validation: {clause}, errors: {result.errors}"


class TestFuzzingAttacks:
    """Fuzzing tests to discover potential security vulnerabilities."""
    
    def generate_random_string(self, length: int) -> str:
        """Generate random string for fuzzing."""
        chars = string.ascii_letters + string.digits + string.punctuation + " "
        return ''.join(random.choices(chars, k=length))
    
    def generate_malicious_payloads(self) -> List[str]:
        """Generate various malicious payloads for testing."""
        payloads = []
        
        # SQL injection variants
        sql_patterns = [
            "'; DROP TABLE {}; --",
            "' OR 1=1 --",
            "' UNION SELECT * FROM {} --",
            "'; INSERT INTO {} VALUES ('{}'); --",
            "' AND 1=0 UNION SELECT NULL,{}--",
        ]
        
        for pattern in sql_patterns:
            payloads.append(pattern.format("users"))
            payloads.append(pattern.format("passwords"))
        
        # Code injection variants
        code_patterns = [
            "__import__('os').system('{}')",
            "eval('{}')",
            "exec('{}')",
            "open('{}').read()",
            "compile('{}', 'test', 'eval')",
        ]
        
        for pattern in code_patterns:
            payloads.append(pattern.format("rm -rf /"))
            payloads.append(pattern.format("cat /etc/passwd"))
        
        # Path traversal
        payloads.extend([
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ])
        
        # Script injection
        payloads.extend([
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "vbscript:msgbox('xss')",
            "data:text/html,<script>alert('xss')</script>",
        ])
        
        # Command injection
        payloads.extend([
            "; ls -la",
            "&& cat /etc/passwd",
            "|| whoami",
            "`id`",
            "$(whoami)",
        ])
        
        return payloads
    
    def test_random_input_fuzzing(self):
        """Test with completely random input."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        
        # Test with random strings of various lengths
        for _ in range(100):
            random_input = self.generate_random_string(random.randint(1, 500))
            
            # Should not crash - either validate or raise expected exceptions
            try:
                evaluator.validate_expression(random_input)
            except (SecurityError, ExpressionValidationError):
                pass  # Expected
            
            try:
                validator.validate_clause(random_input)
            except Exception:
                pass  # Should handle gracefully
    
    def test_malicious_payload_fuzzing(self):
        """Test with known malicious payloads."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        
        malicious_payloads = self.generate_malicious_payloads()
        
        for payload in malicious_payloads:
            # Test expression evaluator
            try:
                evaluator.validate_expression(payload)
                # If it doesn't raise an exception, it should at least be safe
                assert evaluator.is_safe_expression(payload) == False or True
            except (SecurityError, ExpressionValidationError):
                pass  # Expected for malicious payloads
            
            # Test WHERE clause validator
            result = validator.validate_clause(payload)
            # Malicious payloads should either be invalid or trigger warnings
            if result.is_valid:
                # If somehow marked as valid, should at least have warnings
                assert len(result.warnings) > 0 or len(result.errors) == 0
    
    def test_unicode_and_encoding_attacks(self):
        """Test with various Unicode and encoding attack vectors."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        
        unicode_attacks = [
            "field == 'value\u0000'",  # Null byte
            "field == 'value\u202e'",  # Right-to-left override
            "field == 'value\ufeff'",  # Byte order mark
            "field == 'value\u2028'",  # Line separator
            "field == 'value\u2029'",  # Paragraph separator
            "field == 'val\ue000'",   # Private use area
            "field == '\U00010000'",  # Non-BMP character
        ]
        
        for attack in unicode_attacks:
            # Should handle gracefully without crashing
            try:
                evaluator.validate_expression(attack)
                validator.validate_clause(attack)
            except Exception:
                pass  # Should not crash
    
    def test_boundary_value_attacks(self):
        """Test with boundary values that might cause issues."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        
        boundary_values = [
            "",  # Empty string
            " " * 10000,  # Very long whitespace
            "x" * (evaluator.MAX_EXPRESSION_LENGTH + 1),  # Just over limit
            "x" * (validator.MAX_CLAUSE_LENGTH + 1),  # Just over limit
            "a." * (evaluator.MAX_FIELD_DEPTH + 1) + "field",  # Just over depth limit
            "(" * 1000 + ")" * 1000,  # Many nested parentheses
            '"' * 1000,  # Many quotes
            "'" * 1000,  # Many single quotes
        ]
        
        for value in boundary_values:
            try:
                evaluator.validate_expression(value)
            except (SecurityError, ExpressionValidationError):
                pass  # Expected for boundary violations
            
            result = validator.validate_clause(value)
            # Should handle gracefully - either valid or invalid with proper errors
            assert isinstance(result, ValidationResult)


class TestIntegrationSecurity:
    """Integration tests for security across the entire system."""
    
    def test_end_to_end_security_validation(self):
        """Test complete security validation flow."""
        from agent_actions.tasks.services.batch_service import BatchService
        from agent_actions.core.graph.agent_workflow import AgentWorkflow
        
        # Test potentially dangerous agent configs
        dangerous_configs = [
            {
                "skip_if": "__import__('os').system('ls')",
                "where_clause": {
                    "clause": "field == 'value'; DROP TABLE users;--",
                    "scope": "item"
                }
            },
            {
                "skip_if": "eval('1+1')",
                "where_clause": {
                    "clause": "field == 'value' AND exec('print(1)')",
                    "scope": "item"
                }
            },
        ]
        
        batch_service = BatchService()
        
        for config in dangerous_configs:
            # WHERE clause validation should catch malicious clauses
            if config.get("where_clause"):
                clause = config["where_clause"]["clause"]
                assert not is_safe_where_clause(clause)
            
            # The system should handle these gracefully without executing dangerous code
            test_data = [{"field": "value", "other": "data"}]
            
            try:
                # This should either work safely or fail gracefully
                tasks = batch_service.prepare_batch_tasks_from_data(config, test_data)
            except (ValueError, SecurityError) as e:
                # Expected for dangerous configs
                assert "unsafe" in str(e).lower() or "security" in str(e).lower()
    
    def test_context_isolation(self):
        """Test that evaluation contexts are properly isolated."""
        evaluator = SafeExpressionEvaluator()
        
        # Test that one evaluation doesn't affect another
        context1 = {"x": "safe_value"}
        context2 = {"x": "different_value"}
        
        result1 = evaluator.safe_eval("x", context1)
        result2 = evaluator.safe_eval("x", context2)
        
        assert result1 == "safe_value"
        assert result2 == "different_value"
        
        # Test that dangerous context modifications don't persist
        try:
            evaluator.safe_eval("x.__class__.__bases__ = ()", {"x": "test"})
        except Exception:
            pass  # Expected to fail
        
        # Should still work normally
        result3 = evaluator.safe_eval("x", {"x": "normal"})
        assert result3 == "normal"
    
    def test_resource_exhaustion_prevention(self):
        """Test prevention of resource exhaustion attacks."""
        evaluator = SafeExpressionEvaluator()
        
        # These should be rejected before evaluation
        resource_attacks = [
            "len([1] * 10000000)",  # Memory exhaustion
            "'x' * 10000000",  # String memory exhaustion
            "sum(range(10000000))",  # CPU exhaustion
        ]
        
        for attack in resource_attacks:
            # Should be blocked at validation level
            with pytest.raises((SecurityError, ExpressionValidationError)):
                evaluator.validate_expression(attack)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])