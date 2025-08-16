"""
Code injection prevention tests for expression evaluation.

Tests prevention of various code injection attacks through the safe evaluator.
"""

import pytest
from agent_actions.security import (
    SafeExpressionEvaluator, 
    SecurityError, 
    ExpressionValidationError,
    safe_eval
)


class TestCodeInjectionPrevention:
    """Test prevention of code injection attacks."""
    
    def test_import_injection_prevention(self):
        """Test prevention of import-based code injection."""
        import_injections = [
            "__import__('os')",
            "__import__('os').system('ls')",
            "__import__('subprocess').call(['ls'])",
            "__import__('sys').exit(1)",
            "__import__('builtins').eval('1+1')",
            "__import__('builtins').exec('print(1)')",
            "__import__('importlib').import_module('os')",
            "importlib.import_module('os')",
            "import os",
            "from os import system",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in import_injections:
            with pytest.raises(SecurityError, match="Dangerous pattern detected"):
                evaluator.validate_expression(injection)
    
    def test_exec_eval_prevention(self):
        """Test prevention of exec/eval injection."""
        exec_eval_injections = [
            "exec('print(1)')",
            "eval('1+1')",
            "compile('print(1)', 'test', 'exec')",
            "compile('1+1', 'test', 'eval')",
            "exec(compile('print(1)', 'test', 'exec'))",
            "eval(compile('1+1', 'test', 'eval'))",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in exec_eval_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_file_system_access_prevention(self):
        """Test prevention of file system access."""
        file_injections = [
            "open('/etc/passwd')",
            "open('/etc/passwd').read()",
            "open('sensitive.txt', 'w').write('hacked')",
            "file('/etc/passwd')",
            "with open('/etc/passwd') as f: f.read()",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in file_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_attribute_access_prevention(self):
        """Test prevention of dangerous attribute access."""
        attribute_injections = [
            "getattr(str, 'upper')",
            "setattr(obj, 'attr', 'value')",
            "delattr(obj, 'attr')",
            "hasattr(str, 'upper')",
            "dir(str)",
            "vars(obj)",
            "globals()",
            "locals()",
            "callable(str)",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in attribute_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_dunder_method_prevention(self):
        """Test prevention of dunder method access."""
        dunder_injections = [
            "obj.__class__",
            "obj.__dict__",
            "obj.__globals__",
            "obj.__builtins__",
            "obj.__import__",
            "''.__class__.__mro__[2].__subclasses__()",
            "().__class__.__bases__[0].__subclasses__()",
            "[].__class__.__base__.__subclasses__()",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in dunder_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_type_system_manipulation_prevention(self):
        """Test prevention of type system manipulation."""
        type_injections = [
            "type(str)",
            "isinstance('', str)",
            "issubclass(str, object)",
            "super()",
            "classmethod(lambda: None)",
            "staticmethod(lambda: None)",
            "property(lambda: None)",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in type_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_control_flow_injection_prevention(self):
        """Test prevention of control flow injection."""
        control_flow_injections = [
            "for i in range(1000): pass",
            "while True: pass",
            "if True: pass",
            "try: pass\nexcept: pass",
            "with open('file') as f: pass",
            "def evil(): return 1",
            "class Evil: pass",
            "lambda x: x",
            "yield from [1,2,3]",
            "[x for x in range(1000)]",
            "{x: x for x in range(1000)}",
            "(x for x in range(1000))",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in control_flow_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_async_injection_prevention(self):
        """Test prevention of async/await injection."""
        async_injections = [
            "async def evil(): pass",
            "await something()",
            "async with context: pass",
            "async for item in items: pass",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in async_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_nested_evaluation_prevention(self):
        """Test prevention of nested evaluation attacks."""
        nested_injections = [
            "eval(input())",
            "exec(raw_input())",
            "eval('exec(\"print(1)\")')",
            "compile(input(), 'test', 'eval')",
            "__import__('builtins').eval(input())",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in nested_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_string_formatting_injection_prevention(self):
        """Test prevention of string formatting injection."""
        format_injections = [
            "'{}'.format(__import__('os'))",
            "f'{__import__(\"os\")}'",
            "'%s' % __import__('os')",
            "'{0.__class__}'.format('')",
            "'{0.__class__.__mro__}'.format('')",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in format_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_context_pollution_prevention(self):
        """Test prevention of context pollution attacks."""
        evaluator = SafeExpressionEvaluator()
        
        # Test that malicious context doesn't allow code execution
        malicious_contexts = [
            {"__builtins__": {"eval": eval, "exec": exec}},
            {"evil_func": lambda: __import__('os').system('ls')},
            {"__import__": __import__},
            {"globals": globals},
            {"locals": locals},
        ]
        
        for context in malicious_contexts:
            with pytest.raises(SecurityError):
                evaluator.validate_context(context)
    
    def test_indirect_code_execution_prevention(self):
        """Test prevention of indirect code execution."""
        # These attempt to execute code indirectly
        indirect_injections = [
            "x.__class__.__call__",
            "str.__new__.__func__",
            "list.__init__.__func__",
            "().__class__.__call__",
            "''.__class__.__call__",
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for injection in indirect_injections:
            with pytest.raises(SecurityError):
                evaluator.validate_expression(injection)
    
    def test_memory_exhaustion_prevention(self):
        """Test prevention of memory exhaustion attacks."""
        memory_attacks = [
            "' ' * 10**8",  # Large string creation
            "[0] * 10**8",  # Large list creation
            "range(10**8)",  # Large range (though lazy)
            "'x' * (10**20)",  # Astronomically large string
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for attack in memory_attacks:
            # Should be caught at validation level due to suspicious patterns
            # or during evaluation with resource limits
            try:
                evaluator.validate_expression(attack)
                # If validation passes, evaluation should fail or be limited
                result = evaluator.safe_eval(attack, {})
                # If it succeeds, result should be reasonable size
                if isinstance(result, (str, list)):
                    assert len(result) < 1000000, f"Memory attack not prevented: {attack}"
            except (SecurityError, ExpressionValidationError, MemoryError):
                pass  # Expected
    
    def test_legitimate_expressions_work(self):
        """Test that legitimate expressions still work after security measures."""
        legitimate_expressions = [
            ("x == 'test'", {"x": "test"}, True),
            ("len(items) > 0", {"items": [1, 2, 3]}, True),
            ("user.age >= 18", {"user": {"age": 25}}, True),
            ("str(num)", {"num": 42}, "42"),
            ("int(score) + 10", {"score": "80"}, 90),
            ("bool(active)", {"active": 1}, True),
            ("float(rate)", {"rate": "3.14"}, 3.14),
            ("abs(value)", {"value": -5}, 5),
            ("min(numbers)", {"numbers": [1, 2, 3]}, 1),
            ("max(numbers)", {"numbers": [1, 2, 3]}, 3),
            ("sum(values)", {"values": [1, 2, 3]}, 6),
            ("round(pi, 2)", {"pi": 3.14159}, 3.14),
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for expr, context, expected in legitimate_expressions:
            result = evaluator.safe_eval(expr, context)
            assert result == expected, f"Legitimate expression failed: {expr}"
    
    def test_safe_function_whitelist(self):
        """Test that only whitelisted functions are available."""
        evaluator = SafeExpressionEvaluator()
        
        # These should work (whitelisted)
        safe_functions = [
            "len([1, 2, 3])",
            "str(123)",
            "int('456')",
            "float('3.14')",
            "bool(1)",
            "list((1, 2, 3))",
            "dict([('a', 1)])",
            "min([1, 2, 3])",
            "max([1, 2, 3])",
            "sum([1, 2, 3])",
            "abs(-5)",
            "round(3.14159, 2)",
        ]
        
        for func_expr in safe_functions:
            result = evaluator.safe_eval(func_expr, {})
            assert result is not None, f"Safe function failed: {func_expr}"
        
        # These should not work (not whitelisted)
        unsafe_functions = [
            "hex(255)",
            "oct(8)",
            "bin(8)",
            "ord('A')",
            "chr(65)",
            "sorted([3, 1, 2])",
            "reversed([1, 2, 3])",
            "enumerate([1, 2, 3])",
            "zip([1, 2], [3, 4])",
            "map(str, [1, 2, 3])",
            "filter(bool, [0, 1, 2])",
        ]
        
        for func_expr in unsafe_functions:
            with pytest.raises((SecurityError, ExpressionValidationError, NameError, ValueError)):
                evaluator.safe_eval(func_expr, {})
    
    def test_recursive_attack_prevention(self):
        """Test prevention of recursive attacks."""
        # These could cause infinite recursion or stack overflow
        recursive_attacks = [
            "f(f(f(f(f(x)))))",  # Deep recursion (if f was available)
            "x.y.z.a.b.c.d.e.f.g.h.i.j.k.l.m.n.o.p.q.r.s.t.u.v.w.x.y.z",  # Deep attribute access
        ]
        
        evaluator = SafeExpressionEvaluator()
        
        for attack in recursive_attacks:
            # Should be caught by depth limits
            with pytest.raises(SecurityError, match="too deep"):
                evaluator.validate_expression(attack)


class TestContextSecurity:
    """Test security of evaluation contexts."""
    
    def test_context_type_validation(self):
        """Test that context values are properly validated."""
        evaluator = SafeExpressionEvaluator()
        
        # Valid contexts
        valid_contexts = [
            {"x": "string"},
            {"x": 123},
            {"x": 3.14},
            {"x": True},
            {"x": None},
            {"x": [1, 2, 3]},
            {"x": {"nested": "dict"}},
        ]
        
        for context in valid_contexts:
            evaluator.validate_context(context)  # Should not raise
        
        # Invalid contexts
        invalid_contexts = [
            {"x": lambda: None},  # Function
            {"x": open},  # Built-in function
            {"x": type},  # Type object
            {"__builtins__": {}},  # Dangerous key
        ]
        
        for context in invalid_contexts:
            with pytest.raises(SecurityError):
                evaluator.validate_context(context)
    
    def test_context_isolation(self):
        """Test that contexts are properly isolated."""
        evaluator = SafeExpressionEvaluator()
        
        # Test that modifying context doesn't affect evaluator
        context = {"x": [1, 2, 3]}
        result1 = evaluator.safe_eval("len(x)", context)
        
        # Modify context
        context["x"].append(4)
        result2 = evaluator.safe_eval("len(x)", context)
        
        assert result1 == 3
        assert result2 == 4  # Should see the change
        
        # But evaluator's internal state should be clean
        result3 = evaluator.safe_eval("len(y)", {"y": [1, 2]})
        assert result3 == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])