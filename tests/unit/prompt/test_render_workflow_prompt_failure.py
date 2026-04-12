"""Regression tests for render_workflow prompt reference failure handling.

Verifies that _resolve_prompt_fields raises ConfigurationError with
actionable diagnostics when a prompt reference cannot be resolved,
instead of silently keeping the literal $ref string.

Bug: specs/bugs/pending/bug_render_workflow_silent_fallback.md
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.render_workflow import _resolve_prompt_fields


class TestResolvePromptFieldsRaises:
    """_resolve_prompt_fields must raise on load failure, never keep literal $ref."""

    def test_missing_file_raises_configuration_error(self, tmp_path):
        """Missing prompt file raises with reference and key in context."""
        item = {"prompt": "$nonexistent.block_name"}
        with pytest.raises(ConfigurationError) as exc_info:
            _resolve_prompt_fields(item, project_root=tmp_path)

        err = exc_info.value
        assert "$nonexistent.block_name" in str(err)
        assert err.context["prompt_reference"] == "$nonexistent.block_name"
        assert err.context["prompt_key"] == "nonexistent.block_name"
        assert err.cause is not None
        assert isinstance(err.cause, ValueError)

    def test_missing_block_raises_configuration_error(self, tmp_path):
        """Existing file but missing block raises with block name in cause."""
        prompt_dir = tmp_path / "prompt_store"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "myworkflow.md"
        prompt_file.write_text("{prompt existing_block}\nHello\n{end_prompt}\n", encoding="utf-8")

        item = {"prompt": "$myworkflow.missing_block"}
        with pytest.raises(ConfigurationError) as exc_info:
            _resolve_prompt_fields(item, project_root=tmp_path)

        err = exc_info.value
        assert "missing_block" in str(err.cause)
        assert err.context["prompt_key"] == "myworkflow.missing_block"

    def test_invalid_format_no_dot_raises(self, tmp_path):
        """Prompt reference without dot separator raises."""
        item = {"prompt": "$nodot"}
        with pytest.raises(ConfigurationError) as exc_info:
            _resolve_prompt_fields(item, project_root=tmp_path)

        assert "Invalid prompt format" in str(exc_info.value.cause)

    def test_item_not_mutated_before_raise(self, tmp_path):
        """The dict is not mutated to the literal $ref before the error is raised."""
        item = {"prompt": "$nonexistent.block"}
        with pytest.raises(ConfigurationError):
            _resolve_prompt_fields(item, project_root=tmp_path)

        assert item["prompt"] == "$nonexistent.block"

    def test_nested_ref_failure_raises(self, tmp_path):
        """Prompt ref nested inside action config raises, not silently passes."""
        config = {
            "actions": [
                {"name": "step1", "prompt": "$missing.ref"},
            ]
        }
        with pytest.raises(ConfigurationError) as exc_info:
            _resolve_prompt_fields(config, project_root=tmp_path)

        assert exc_info.value.context["prompt_reference"] == "$missing.ref"

    def test_deeply_nested_ref_failure_raises(self, tmp_path):
        """Deeply nested prompt ref in list-of-dicts raises."""
        config = [{"actions": [{"steps": [{"prompt": "$deep.missing"}]}]}]
        with pytest.raises(ConfigurationError):
            _resolve_prompt_fields(config, project_root=tmp_path)


class TestResolvePromptFieldsSuccess:
    """Valid references still resolve correctly after the fix."""

    def test_valid_reference_resolves(self, tmp_path):
        """Valid $workflow.block resolves to prompt content."""
        prompt_dir = tmp_path / "prompt_store"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "myworkflow.md"
        prompt_file.write_text("{prompt greet}\nHello, world!\n{end_prompt}\n", encoding="utf-8")

        item = {"prompt": "$myworkflow.greet"}
        _resolve_prompt_fields(item, project_root=tmp_path)
        assert item["prompt"] == "Hello, world!"

    def test_valid_reference_with_extra_args(self, tmp_path):
        """Valid reference with trailing extra text appends it."""
        prompt_dir = tmp_path / "prompt_store"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "myworkflow.md"
        prompt_file.write_text("{prompt greet}\nHello\n{end_prompt}\n", encoding="utf-8")

        item = {"prompt": "$myworkflow.greet extra_arg"}
        _resolve_prompt_fields(item, project_root=tmp_path)
        assert item["prompt"] == "Hello extra_arg"

    def test_non_ref_prompt_unchanged(self):
        """Prompt values that don't start with $ are left alone."""
        item = {"prompt": "Just a normal prompt"}
        _resolve_prompt_fields(item)
        assert item["prompt"] == "Just a normal prompt"

    def test_non_prompt_keys_unchanged(self):
        """Non-prompt keys are never resolved, even if they start with $."""
        item = {"description": "$something.ref", "name": "test"}
        _resolve_prompt_fields(item)
        assert item["description"] == "$something.ref"

    def test_empty_dict_no_error(self):
        """Empty dict doesn't raise."""
        _resolve_prompt_fields({})

    def test_empty_list_no_error(self):
        """Empty list doesn't raise."""
        _resolve_prompt_fields([])

    def test_non_string_prompt_unchanged(self):
        """Non-string prompt value (e.g. dict) is left alone."""
        item = {"prompt": {"inline": "value"}}
        _resolve_prompt_fields(item)
        assert item["prompt"] == {"inline": "value"}


class TestErrorMessageQuality:
    """Error messages must be actionable — include file, block, and cause."""

    def test_error_includes_original_reference(self, tmp_path):
        """The error message includes the exact $ref that failed."""
        item = {"prompt": "$workflows.analyze"}
        with pytest.raises(ConfigurationError, match=r"\$workflows\.analyze"):
            _resolve_prompt_fields(item, project_root=tmp_path)

    def test_error_context_has_operation(self, tmp_path):
        """Context includes operation name for log correlation."""
        item = {"prompt": "$missing.ref"}
        with pytest.raises(ConfigurationError) as exc_info:
            _resolve_prompt_fields(item, project_root=tmp_path)

        assert exc_info.value.context["operation"] == "resolve_prompt_field"

    def test_cause_chain_preserved(self, tmp_path):
        """The original ValueError is preserved as __cause__ for traceback."""
        item = {"prompt": "$missing.ref"}
        with pytest.raises(ConfigurationError) as exc_info:
            _resolve_prompt_fields(item, project_root=tmp_path)

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ValueError)
