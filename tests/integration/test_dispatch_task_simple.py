"""Integration tests for simplified dispatch_task() design.

dispatch_task() now has a simple design:
- Takes only a function name: dispatch_task('function_name')
- The function receives the same context_data that the LLM receives
- No additional arguments allowed
"""
import json
import pytest
from agent_actions.agents.transformers.prompt_utils import PromptUtils
from agent_actions.agents.base.agent_builder import _build_field_context_from_context_data


class TestDispatchTaskSimpleDesign:
    """Test the simplified dispatch_task() design with no arguments."""

    def test_dispatch_with_single_quotes(self, tmp_path):
        """Test dispatch_task('function_name') with single quotes."""
        # Create UDF module
        udf_path = tmp_path / "simple_func.py"
        udf_path.write_text("""
def simple_func(context_data):
    # Function receives the same context_data as the LLM
    import json
    data = json.loads(context_data)
    return f"Processed: {data['content']}"
""")

        prompt = "Result: dispatch_task('simple_func')"
        context_data = {"content": "test data", "id": "123"}

        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        assert 'Processed: test data' in processed_prompt
        assert 'dispatch_task' not in processed_prompt

    def test_dispatch_with_double_quotes(self, tmp_path):
        """Test dispatch_task("function_name") with double quotes."""
        # Create UDF module
        udf_path = tmp_path / "double_quote_func.py"
        udf_path.write_text("""
def double_quote_func(context_data):
    import json
    data = json.loads(context_data)
    return f"Got: {data['value']}"
""")

        prompt = 'Result: dispatch_task("double_quote_func")'
        context_data = {"value": "hello world"}

        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        assert 'Got: hello world' in processed_prompt
        assert 'dispatch_task' not in processed_prompt

    def test_dispatch_receives_full_context(self, tmp_path):
        """Verify function receives the same context as LLM."""
        # Create UDF that echoes all context fields
        udf_path = tmp_path / "echo_context.py"
        udf_path.write_text("""
def echo_context(context_data):
    import json
    data = json.loads(context_data)
    keys = sorted(data.keys())
    return f"Keys: {', '.join(keys)}"
""")

        prompt = "dispatch_task('echo_context')"
        context_data = {
            "content": "text",
            "title": "Test",
            "metadata": {"author": "John"},
            "id": "456"
        }

        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        # Function should see all fields
        assert 'Keys: content, id, metadata, title' in processed_prompt

    def test_multiple_dispatch_calls(self, tmp_path):
        """Test multiple dispatch_task() calls in one prompt."""
        # Create two UDF modules
        udf1_path = tmp_path / "func_one.py"
        udf1_path.write_text("""
def func_one(context_data):
    return "FIRST"
""")

        udf2_path = tmp_path / "func_two.py"
        udf2_path.write_text("""
def func_two(context_data):
    return "SECOND"
""")

        prompt = "A: dispatch_task('func_one'), B: dispatch_task('func_two')"
        context_data = {"data": "test"}

        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        assert 'A: FIRST, B: SECOND' in processed_prompt
        assert 'dispatch_task' not in processed_prompt

    def test_dispatch_with_field_references(self, tmp_path):
        """Test dispatch_task() combined with field reference replacement."""
        # Create UDF
        udf_path = tmp_path / "process_data.py"
        udf_path.write_text("""
def process_data(context_data):
    import json
    data = json.loads(context_data)
    return f"Uppercase: {data['content'].upper()}"
""")

        # Prompt with both field reference and dispatch_task
        prompt = "Title: {source.title}, Result: dispatch_task('process_data')"
        context_data = {"title": "My Doc", "content": "hello"}

        # Step 1: Replace field references
        field_context = {'source': context_data}
        prompt_after_fields = PromptUtils.replace_field_references(prompt, field_context)

        # Step 2: Process dispatch_task
        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt_after_fields,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        assert 'Title: My Doc' in processed_prompt
        assert 'Uppercase: HELLO' in processed_prompt
        assert 'dispatch_task' not in processed_prompt
        assert '{source.title}' not in processed_prompt

    def test_dispatch_in_multiline_prompt(self, tmp_path):
        """Test dispatch_task() works across multiple lines."""
        # Create UDF
        udf_path = tmp_path / "count_lines.py"
        udf_path.write_text("""
def count_lines(context_data):
    import json
    data = json.loads(context_data)
    text = data.get('text', '')
    line_count = len(text.split('\\n'))
    return f"{line_count} lines"
""")

        # Multi-line prompt
        prompt = """Process the document:
dispatch_task('count_lines')

Additional info here."""

        context_data = {"text": "Line 1\nLine 2\nLine 3"}

        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        assert '3 lines' in processed_prompt
        assert 'dispatch_task' not in processed_prompt

    def test_dispatch_function_not_found_error(self, tmp_path):
        """Test error handling when function doesn't exist."""
        prompt = "dispatch_task('nonexistent_function')"
        context_data = {"data": "test"}

        with pytest.raises(Exception) as exc_info:
            PromptUtils.inject_function_outputs_into_prompt(
                prompt,
                tools_path=str(tmp_path),
                context_data_str=json.dumps(context_data)
            )

        # Should raise an error about missing module/function
        assert 'nonexistent_function' in str(exc_info.value).lower()

    def test_dispatch_with_captured_results(self, tmp_path):
        """Test add_dispatch flag to capture function outputs."""
        # Create UDF
        udf_path = tmp_path / "compute_value.py"
        udf_path.write_text("""
def compute_value(context_data):
    return "42"
""")

        prompt = "dispatch_task('compute_value')"
        context_data = {"data": "test"}
        agent_config = {"add_dispatch": True}

        processed_prompt, captured = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data),
            agent_config=agent_config
        )

        # Check captured results
        assert 'compute_value' in captured
        assert captured['compute_value'] == "42"
        assert processed_prompt == "42"


class TestDispatchTaskEdgeCases:
    """Test edge cases for dispatch_task()."""

    def test_dispatch_no_spaces(self, tmp_path):
        """Test dispatch_task with no spaces."""
        udf_path = tmp_path / "no_space.py"
        udf_path.write_text("""
def no_space(context_data):
    return "OK"
""")

        prompt = "dispatch_task('no_space')"
        context_data = {}

        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        assert processed_prompt == "OK"

    def test_dispatch_with_spaces(self, tmp_path):
        """Test dispatch_task with extra spaces."""
        udf_path = tmp_path / "with_space.py"
        udf_path.write_text("""
def with_space(context_data):
    return "OK"
""")

        prompt = "dispatch_task(  'with_space'  )"
        context_data = {}

        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        # Pattern won't match with spaces - this is expected behavior
        # The pattern is strict: dispatch_task('func') or dispatch_task("func")
        assert 'dispatch_task' in processed_prompt  # Not processed

    def test_dispatch_function_returns_none(self, tmp_path):
        """Test handling when function returns None."""
        udf_path = tmp_path / "returns_none.py"
        udf_path.write_text("""
def returns_none(context_data):
    return None
""")

        prompt = "dispatch_task('returns_none')"
        context_data = {}

        processed_prompt, _ = PromptUtils.inject_function_outputs_into_prompt(
            prompt,
            tools_path=str(tmp_path),
            context_data_str=json.dumps(context_data)
        )

        assert 'Error: No valid return from function' in processed_prompt
