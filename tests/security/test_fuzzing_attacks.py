"""
Fuzzing tests for security validation.

Comprehensive fuzzing tests to discover potential security vulnerabilities
through automated generation of malicious and edge-case inputs.
"""

import pytest
import string
import random
import itertools
from typing import List, Iterator, Tuple

from agent_actions.security import (
    SafeExpressionEvaluator,
    WhereClauseValidator,
    SecurityError,
    ExpressionValidationError,
    safe_eval,
    validate_where_clause
)


class FuzzingTestGenerator:
    """Generator for fuzzing test cases."""
    
    @staticmethod
    def generate_random_strings(count: int = 100, min_len: int = 1, max_len: int = 200) -> Iterator[str]:
        """Generate random strings with various character sets."""
        char_sets = [
            string.ascii_letters,
            string.digits,
            string.punctuation,
            string.whitespace,
            string.ascii_letters + string.digits,
            string.ascii_letters + string.punctuation,
            string.printable,
            # Unicode ranges
            ''.join(chr(i) for i in range(0x100, 0x200)),  # Latin Extended-A
            ''.join(chr(i) for i in range(0x2000, 0x2100)),  # General Punctuation
        ]
        
        for _ in range(count):
            length = random.randint(min_len, max_len)
            char_set = random.choice(char_sets)
            yield ''.join(random.choices(char_set, k=length))
    
    @staticmethod
    def generate_injection_patterns() -> List[str]:
        """Generate common injection patterns."""
        base_patterns = [
            # SQL injection patterns
            "'; DROP TABLE {}; --",
            "' OR 1=1 --",
            "' UNION SELECT * FROM {} --",
            "'; INSERT INTO {} VALUES ('{}'); --",
            "' AND 1=0 UNION SELECT NULL,{}--",
            
            # Code injection patterns
            "__import__('{}').system('{}')",
            "eval('{}')",
            "exec('{}')",
            "open('{}').read()",
            "compile('{}', 'test', 'eval')",
            
            # Path traversal
            "../{}/{}",
            "..\\{}\\{}",
            "%2e%2e%2f{}",
            
            # Script injection
            "<script>{}</script>",
            "javascript:{}",
            "vbscript:{}",
            "data:text/html,{}",
            
            # Command injection
            "; {}",
            "&& {}",
            "|| {}",
            "`{}`",
            "$({}) ",
            
            # Format string attacks
            "%s%s%s%s",
            "%x%x%x%x",
            "%n%n%n%n",
            "{}.{}.__class__",
            "{0.__class__.__mro__}",
        ]
        
        payloads = []
        for pattern in base_patterns:
            # Fill placeholders with common targets
            targets = ["users", "admin", "passwords", "config", "etc/passwd", "system", "ls", "id", "whoami"]
            try:
                if pattern.count('{}') == 1:
                    payloads.extend([pattern.format(target) for target in targets])
                elif pattern.count('{}') == 2:
                    payloads.extend([pattern.format(t1, t2) for t1, t2 in itertools.combinations(targets, 2)])
            except:
                payloads.append(pattern)  # Add as-is if formatting fails
        
        return payloads
    
    @staticmethod
    def generate_unicode_attacks() -> List[str]:
        """Generate Unicode-based attack vectors."""
        return [
            # Null bytes and control characters
            "field\x00value",
            "field\x01value",
            "field\x1fvalue",
            
            # Unicode normalization attacks
            "field\u0041\u030avalue",  # A with ring above
            "field\u00c5value",        # Precomposed A with ring
            
            # Directional override attacks
            "field\u202evalueevil",    # Right-to-left override
            "field\u200evalueevil",    # Left-to-right mark
            
            # Zero-width characters
            "field\u200bvalue",        # Zero-width space
            "field\u200cvalue",        # Zero-width non-joiner
            "field\u200dvalue",        # Zero-width joiner
            "field\ufeffvalue",        # Byte order mark
            
            # Line/paragraph separators
            "field\u2028value",        # Line separator
            "field\u2029value",        # Paragraph separator
            
            # Private use area
            "field\ue000value",
            "field\uf8ffvalue",
            
            # Non-BMP characters
            "field\U00010000value",
            "field\U0001f4a9value",    # Pile of poo emoji
            
            # Combining characters
            "field\u0300\u0301\u0302value",  # Multiple combining marks
            
            # Homograph attacks
            "admin",                   # Regular
            "\u0430dmin",             # Cyrillic 'a'
            "a\u0501min",             # Different 'd' variant
            
            # Lookalike characters
            "fie1d",                   # '1' instead of 'l'
            "fie|d",                   # '|' instead of 'l'
            "fie\u0456d",             # Ukrainian 'i' instead of 'l'
        ]
    
    @staticmethod
    def generate_boundary_values() -> List[str]:
        """Generate boundary and edge case values."""
        return [
            "",                        # Empty string
            " ",                       # Single space
            "  ",                      # Multiple spaces
            "\t",                      # Tab
            "\n",                      # Newline
            "\r\n",                    # Windows line ending
            "\x00",                    # Null byte
            "A" * 1000,                # Long string
            "A" * 10000,               # Very long string
            "(" * 1000,                # Many opening parens
            ")" * 1000,                # Many closing parens
            "'" * 1000,                # Many single quotes
            '"' * 1000,                # Many double quotes
            "\\" * 1000,               # Many backslashes
            "." * 1000,                # Many dots (for field access)
            "a." * 100 + "field",      # Deep field access
            "1" * 1000,                # Long number string
            "-" * 1000,                # Many dashes
            "=" * 1000,                # Many equals
            "&" * 1000,                # Many ampersands
            "|" * 1000,                # Many pipes
            "<" * 1000,                # Many less-than
            ">" * 1000,                # Many greater-than
        ]
    
    @staticmethod
    def generate_nested_structures() -> List[str]:
        """Generate deeply nested or complex structures."""
        structures = []
        
        # Nested parentheses
        for depth in [10, 50, 100]:
            nested = "(" * depth + "field == 'value'" + ")" * depth
            structures.append(nested)
        
        # Nested field access
        for depth in [5, 10, 20]:
            nested_field = ".".join([f"level{i}" for i in range(depth)])
            structures.append(f"{nested_field} == 'value'")
        
        # Complex boolean expressions
        complex_expr = " AND ".join([f"field{i} == 'value{i}'" for i in range(50)])
        structures.append(complex_expr)
        
        # Mixed nesting
        structures.extend([
            "((field1 == 'value1') AND (field2 == 'value2')) OR ((field3 == 'value3') AND (field4 == 'value4'))",
            "field.a.b.c == 'test' AND other.x.y.z != 'bad' OR third.p.q.r CONTAINS 'good'",
            "NOT (NOT (NOT (field == 'value')))",
        ])
        
        return structures


class TestFuzzingAttacks:
    """Comprehensive fuzzing tests for security vulnerabilities."""
    
    def test_random_input_fuzzing(self):
        """Test with completely random inputs."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        generator = FuzzingTestGenerator()
        
        # Test with random strings
        for random_input in generator.generate_random_strings(count=50, max_len=100):
            # Test expression evaluator
            try:
                evaluator.validate_expression(random_input)
                # If validation passes, try evaluation with empty context
                result = evaluator.safe_eval(random_input, {})
                # Should return a reasonable result
                assert result is not None
            except (SecurityError, ExpressionValidationError, ValueError, NameError):
                pass  # Expected for random input
            except Exception as e:
                # Should not crash with unexpected exceptions
                pytest.fail(f"Unexpected exception for input '{random_input[:50]}...': {e}")
            
            # Test WHERE clause validator
            try:
                result = validator.validate_clause(random_input)
                assert isinstance(result.is_valid, bool)
                assert isinstance(result.errors, list)
                assert isinstance(result.warnings, list)
            except Exception as e:
                pytest.fail(f"WHERE validator crashed on input '{random_input[:50]}...': {e}")
    
    def test_injection_pattern_fuzzing(self):
        """Test with known injection patterns."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        generator = FuzzingTestGenerator()
        
        injection_patterns = generator.generate_injection_patterns()
        
        for pattern in injection_patterns:
            # Expression evaluator should reject malicious patterns
            try:
                evaluator.validate_expression(pattern)
                # If somehow validation passes, evaluation should be safe
                result = evaluator.safe_eval(pattern, {})
                # Should not execute dangerous operations
                assert not self._is_dangerous_result(result)
            except (SecurityError, ExpressionValidationError):
                pass  # Expected for injection patterns
            except Exception as e:
                # Should handle gracefully
                assert not self._is_system_compromise(str(e))
            
            # WHERE clause validator should detect or handle safely
            try:
                result = validator.validate_clause(pattern)
                if result.is_valid:
                    # If marked as valid, should have warnings or be actually safe
                    assert len(result.warnings) > 0 or self._is_actually_safe_pattern(pattern)
            except Exception as e:
                # Should not crash
                pytest.fail(f"WHERE validator crashed on injection pattern '{pattern[:50]}...': {e}")
    
    def test_unicode_attack_fuzzing(self):
        """Test with Unicode-based attacks."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        generator = FuzzingTestGenerator()
        
        unicode_attacks = generator.generate_unicode_attacks()
        
        for attack in unicode_attacks:
            # Should handle Unicode gracefully
            try:
                evaluator.validate_expression(attack)
                validator.validate_clause(attack)
            except (SecurityError, ExpressionValidationError, UnicodeError):
                pass  # May reject Unicode attacks
            except Exception as e:
                # Should not crash on Unicode input
                pytest.fail(f"Unicode handling failed for '{repr(attack)}': {e}")
    
    def test_boundary_value_fuzzing(self):
        """Test with boundary and edge case values."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        generator = FuzzingTestGenerator()
        
        boundary_values = generator.generate_boundary_values()
        
        for value in boundary_values:
            # Test expression evaluator
            try:
                evaluator.validate_expression(value)
                # If validation passes, try evaluation
                result = evaluator.safe_eval(value, {"field": "test", "A": "test"})
            except (SecurityError, ExpressionValidationError, ValueError, NameError):
                pass  # Expected for boundary values
            except MemoryError:
                pass  # Expected for very large inputs
            except Exception as e:
                # Should handle boundary cases gracefully
                if "recursion" not in str(e).lower():  # Allow recursion errors for deep nesting
                    pytest.fail(f"Boundary value handling failed for '{repr(value[:50])}': {e}")
            
            # Test WHERE clause validator
            try:
                result = validator.validate_clause(value)
                assert isinstance(result, type(validator.validate_clause("")))
            except MemoryError:
                pass  # Expected for very large inputs
            except Exception as e:
                pytest.fail(f"WHERE validator boundary handling failed for '{repr(value[:50])}': {e}")
    
    def test_nested_structure_fuzzing(self):
        """Test with deeply nested or complex structures."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        generator = FuzzingTestGenerator()
        
        nested_structures = generator.generate_nested_structures()
        
        for structure in nested_structures:
            # Test expression evaluator
            try:
                evaluator.validate_expression(structure)
            except (SecurityError, ExpressionValidationError):
                pass  # Expected for complex structures
            except RecursionError:
                pass  # Expected for deeply nested structures
            except Exception as e:
                pytest.fail(f"Nested structure handling failed for '{structure[:100]}...': {e}")
            
            # Test WHERE clause validator
            try:
                result = validator.validate_clause(structure)
                # Should handle complex structures without crashing
                assert hasattr(result, 'is_valid')
            except RecursionError:
                pass  # Expected for deeply nested structures
            except Exception as e:
                pytest.fail(f"WHERE validator nested handling failed for '{structure[:100]}...': {e}")
    
    def test_mutation_fuzzing(self):
        """Test by mutating valid inputs."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        
        # Start with valid inputs
        valid_inputs = [
            "field == 'value'",
            "age >= 18",
            "status != 'inactive'",
            "category IN ['tech', 'science']",
            "user.profile.verified == true",
        ]
        
        mutation_strategies = [
            self._insert_random_chars,
            self._delete_random_chars,
            self._substitute_random_chars,
            self._duplicate_substrings,
            self._reverse_substrings,
            self._insert_injection_payload,
        ]
        
        for valid_input in valid_inputs:
            for strategy in mutation_strategies:
                for _ in range(10):  # 10 mutations per strategy
                    mutated = strategy(valid_input)
                    
                    # Test expression evaluator
                    try:
                        evaluator.validate_expression(mutated)
                        evaluator.safe_eval(mutated, {"field": "value", "age": 25, "status": "active", 
                                                    "category": "tech", "user": {"profile": {"verified": True}}})
                    except (SecurityError, ExpressionValidationError, ValueError, NameError, SyntaxError):
                        pass  # Expected for mutations
                    except Exception as e:
                        pytest.fail(f"Mutation fuzzing failed for '{mutated[:50]}...': {e}")
                    
                    # Test WHERE clause validator
                    try:
                        validator.validate_clause(mutated)
                    except Exception as e:
                        pytest.fail(f"WHERE validator mutation fuzzing failed for '{mutated[:50]}...': {e}")
    
    def _is_dangerous_result(self, result) -> bool:
        """Check if a result indicates dangerous operation."""
        if result is None:
            return False
        
        # Check for signs of system access
        dangerous_indicators = [
            "passwd", "shadow", "system", "root", "admin",
            "/etc/", "/tmp/", "C:\\", "cmd.exe", "sh",
            "python", "import", "exec", "eval"
        ]
        
        result_str = str(result).lower()
        return any(indicator in result_str for indicator in dangerous_indicators)
    
    def _is_system_compromise(self, error_msg: str) -> bool:
        """Check if error message indicates system compromise."""
        compromise_indicators = [
            "executed", "imported", "opened file", "system call",
            "shell command", "process started"
        ]
        
        error_lower = error_msg.lower()
        return any(indicator in error_lower for indicator in compromise_indicators)
    
    def _is_actually_safe_pattern(self, pattern: str) -> bool:
        """Check if a pattern is actually safe despite containing keywords."""
        # Simple heuristic - patterns that are just field comparisons
        safe_patterns = [
            "field == 'union'",  # Contains 'UNION' but is just a value
            "status == 'select'",  # Contains 'SELECT' but is just a value
            "type == 'drop'",  # Contains 'DROP' but is just a value
        ]
        
        return any(safe in pattern.lower() for safe in safe_patterns)
    
    # Mutation strategy helpers
    def _insert_random_chars(self, text: str) -> str:
        """Insert random characters at random positions."""
        if not text:
            return text
        
        pos = random.randint(0, len(text))
        char = random.choice(string.printable)
        return text[:pos] + char + text[pos:]
    
    def _delete_random_chars(self, text: str) -> str:
        """Delete random characters."""
        if len(text) <= 1:
            return text
        
        pos = random.randint(0, len(text) - 1)
        return text[:pos] + text[pos + 1:]
    
    def _substitute_random_chars(self, text: str) -> str:
        """Substitute random characters."""
        if not text:
            return text
        
        pos = random.randint(0, len(text) - 1)
        char = random.choice(string.printable)
        return text[:pos] + char + text[pos + 1:]
    
    def _duplicate_substrings(self, text: str) -> str:
        """Duplicate random substrings."""
        if len(text) < 2:
            return text
        
        start = random.randint(0, len(text) - 2)
        end = random.randint(start + 1, len(text))
        substring = text[start:end]
        pos = random.randint(0, len(text))
        return text[:pos] + substring + text[pos:]
    
    def _reverse_substrings(self, text: str) -> str:
        """Reverse random substrings."""
        if len(text) < 2:
            return text
        
        start = random.randint(0, len(text) - 2)
        end = random.randint(start + 1, len(text))
        return text[:start] + text[start:end][::-1] + text[end:]
    
    def _insert_injection_payload(self, text: str) -> str:
        """Insert injection payloads."""
        payloads = ["'; DROP TABLE x;--", "OR 1=1", "__import__('os')", "eval('1')"]
        payload = random.choice(payloads)
        pos = random.randint(0, len(text))
        return text[:pos] + payload + text[pos:]


class TestStressConditions:
    """Test under stress conditions."""
    
    def test_high_volume_validation(self):
        """Test with high volume of validation requests."""
        evaluator = SafeExpressionEvaluator()
        validator = WhereClauseValidator()
        
        # Generate many inputs quickly
        inputs = [f"field{i} == 'value{i}'" for i in range(1000)]
        
        for input_expr in inputs:
            try:
                evaluator.validate_expression(input_expr)
                validator.validate_clause(input_expr)
            except Exception as e:
                pytest.fail(f"High volume test failed: {e}")
    
    def test_concurrent_validation(self):
        """Test concurrent validation (if threading is used)."""
        import threading
        import queue
        
        evaluator = SafeExpressionEvaluator()
        results = queue.Queue()
        errors = queue.Queue()
        
        def validate_expressions():
            try:
                for i in range(100):
                    expr = f"field{i} == 'value{i}'"
                    evaluator.validate_expression(expr)
                    results.put(f"thread_{threading.current_thread().ident}_success")
            except Exception as e:
                errors.put(f"thread_{threading.current_thread().ident}_error: {e}")
        
        # Start multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=validate_expressions)
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Check results
        assert results.qsize() == 500  # 5 threads * 100 expressions each
        assert errors.qsize() == 0, f"Concurrent validation errors: {list(errors.queue)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])