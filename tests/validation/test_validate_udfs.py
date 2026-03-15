"""Tests for ValidateUDFsCommand — UDF validation without running workflows."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest

from agent_actions.errors import (
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError,
)
from agent_actions.validation.validate_udfs import ValidateUDFsCommand

# ---------------------------------------------------------------------------
# _count_impl_references (pure function — no mocking)
# ---------------------------------------------------------------------------


class TestCountImplReferences:
    def _make_cmd(self) -> ValidateUDFsCommand:
        return ValidateUDFsCommand.__new__(ValidateUDFsCommand)

    def test_nested_dict_with_impl_keys(self):
        cmd = self._make_cmd()
        config = {
            "actions": {
                "step1": {"impl": "my_func"},
                "step2": {"impl": "other_func"},
            }
        }
        assert cmd._count_impl_references(config) == {"my_func", "other_func"}

    def test_no_impl_keys_returns_empty(self):
        cmd = self._make_cmd()
        assert cmd._count_impl_references({"key": "value", "nested": {"a": 1}}) == set()

    def test_impl_in_lists(self):
        cmd = self._make_cmd()
        config = {"steps": [{"impl": "func_a"}, {"impl": "func_b"}]}
        assert cmd._count_impl_references(config) == {"func_a", "func_b"}

    def test_impl_value_not_string_skipped(self):
        cmd = self._make_cmd()
        config = {"impl": 42, "nested": {"impl": ["not", "a", "string"]}}
        assert cmd._count_impl_references(config) == set()

    def test_deeply_nested(self):
        cmd = self._make_cmd()
        config = {"a": {"b": {"c": {"d": {"impl": "deep_func"}}}}}
        assert cmd._count_impl_references(config) == {"deep_func"}

    def test_empty_config(self):
        cmd = self._make_cmd()
        assert cmd._count_impl_references({}) == set()

    def test_mixed_lists_and_dicts(self):
        cmd = self._make_cmd()
        config = {
            "pipelines": [
                {"stages": [{"impl": "a"}, {"other": "b"}]},
                {"impl": "c"},
            ]
        }
        assert cmd._count_impl_references(config) == {"a", "c"}


# ---------------------------------------------------------------------------
# validate() — mock external dependencies
# ---------------------------------------------------------------------------

# Common patch targets
_PATHS_FACTORY = "agent_actions.validation.validate_udfs.ProjectPathsFactory"
_CONFIG_MANAGER = "agent_actions.validation.validate_udfs.ConfigManager"
_DISCOVER = "agent_actions.validation.validate_udfs.discover_udfs"
_VALIDATE_REFS = "agent_actions.validation.validate_udfs.validate_udf_references"
_CLEAR_REGISTRY = "agent_actions.validation.validate_udfs.clear_registry"


def _mock_paths(tmp_path: Path, agent_name: str = "my_agent") -> MagicMock:
    """Return a mock ProjectPaths with real filesystem paths."""
    config_dir = tmp_path / "configs"
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / f"{agent_name}.yml"
    config_file.write_text("actions: {}")

    paths = MagicMock()
    paths.agent_config_dir = config_dir
    paths.default_config_path = tmp_path / "defaults.yml"
    return paths


class TestValidate:
    @patch(_CLEAR_REGISTRY)
    @patch(_VALIDATE_REFS)
    @patch(_DISCOVER)
    @patch(_CONFIG_MANAGER)
    @patch(_PATHS_FACTORY)
    def test_happy_path(
        self, mock_pf, mock_cm_cls, mock_discover, mock_validate_refs, mock_clear, tmp_path
    ):
        mock_pf.create_project_paths.return_value = _mock_paths(tmp_path)
        mock_discover.return_value = {"func_a": {}, "func_b": {}}

        cm_instance = MagicMock()
        cm_instance.user_config = {"actions": {"s": {"impl": "func_a"}}}
        mock_cm_cls.return_value = cm_instance

        cmd = ValidateUDFsCommand("my_agent.yml", str(tmp_path))
        result = cmd.validate()

        assert result["valid"] is True
        assert result["registry"] == {"func_a": {}, "func_b": {}}
        assert result["impl_refs"] == {"func_a"}
        mock_clear.assert_called_once()

    @patch(_CLEAR_REGISTRY)
    @patch(_PATHS_FACTORY)
    def test_config_file_not_found(self, mock_pf, mock_clear, tmp_path):
        paths = MagicMock()
        paths.agent_config_dir = tmp_path / "missing"
        paths.agent_config_dir.mkdir()
        paths.default_config_path = tmp_path / "defaults.yml"
        mock_pf.create_project_paths.return_value = paths

        cmd = ValidateUDFsCommand("my_agent.yml", str(tmp_path))
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            cmd.validate()

    @patch(_CLEAR_REGISTRY)
    @patch(_DISCOVER)
    @patch(_PATHS_FACTORY)
    def test_duplicate_function_error(self, mock_pf, mock_discover, mock_clear, tmp_path):
        mock_pf.create_project_paths.return_value = _mock_paths(tmp_path)
        mock_discover.side_effect = DuplicateFunctionError(
            function_name="dup_func",
            existing_location="mod_a",
            existing_file="a.py",
            new_location="mod_b",
            new_file="b.py",
        )

        cmd = ValidateUDFsCommand("my_agent.yml", str(tmp_path))
        result = cmd.validate()

        assert result["valid"] is False
        assert result["error_type"] == "duplicate"
        assert isinstance(result["error"], DuplicateFunctionError)

    @patch(_CLEAR_REGISTRY)
    @patch(_DISCOVER)
    @patch(_PATHS_FACTORY)
    def test_udf_load_error(self, mock_pf, mock_discover, mock_clear, tmp_path):
        mock_pf.create_project_paths.return_value = _mock_paths(tmp_path)
        mock_discover.side_effect = UDFLoadError(
            module="bad_module", file="bad.py", error="SyntaxError"
        )

        cmd = ValidateUDFsCommand("my_agent.yml", str(tmp_path))
        result = cmd.validate()

        assert result["valid"] is False
        assert result["error_type"] == "load_error"

    @patch(_CLEAR_REGISTRY)
    @patch(_VALIDATE_REFS)
    @patch(_DISCOVER)
    @patch(_CONFIG_MANAGER)
    @patch(_PATHS_FACTORY)
    def test_function_not_found_error(
        self, mock_pf, mock_cm_cls, mock_discover, mock_validate_refs, mock_clear, tmp_path
    ):
        mock_pf.create_project_paths.return_value = _mock_paths(tmp_path)
        mock_discover.return_value = {}
        cm_instance = MagicMock()
        cm_instance.user_config = {"actions": {"s": {"impl": "missing"}}}
        mock_cm_cls.return_value = cm_instance
        mock_validate_refs.side_effect = FunctionNotFoundError(
            "Function 'missing' not found",
            context={"function_name": "missing", "available_functions": []},
        )

        cmd = ValidateUDFsCommand("my_agent.yml", str(tmp_path))
        result = cmd.validate()

        assert result["valid"] is False
        assert result["error_type"] == "not_found"

    @patch(_CLEAR_REGISTRY)
    @patch(_VALIDATE_REFS)
    @patch(_DISCOVER)
    @patch(_CONFIG_MANAGER)
    @patch(_PATHS_FACTORY)
    def test_config_is_none_uses_empty_dict(
        self, mock_pf, mock_cm_cls, mock_discover, mock_validate_refs, mock_clear, tmp_path
    ):
        mock_pf.create_project_paths.return_value = _mock_paths(tmp_path)
        mock_discover.return_value = {}
        cm_instance = MagicMock()
        cm_instance.user_config = None
        mock_cm_cls.return_value = cm_instance

        cmd = ValidateUDFsCommand("my_agent.yml", str(tmp_path))
        result = cmd.validate()

        assert result["valid"] is True
        # validate_udf_references called with empty dict
        mock_validate_refs.assert_called_once_with({})


# ---------------------------------------------------------------------------
# execute() — mock validate() return + console
# ---------------------------------------------------------------------------


class TestExecute:
    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_valid_result_prints_success(self, mock_fire, tmp_path):
        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": {"fn": {}},
                "impl_refs": {"fn"},
            }
        )

        with patch("agent_actions.validation.validate_udfs.get_udf_metadata") as mock_meta:
            mock_meta.return_value = {"file": "tools.py"}
            cmd.execute()

        # Check that success message was printed
        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert any("All UDF references valid" in c for c in calls)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_duplicate_error_calls_handler(self, mock_fire, tmp_path):
        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        dup_err = DuplicateFunctionError(
            function_name="dup",
            existing_location="a",
            existing_file="a.py",
            new_location="b",
            new_file="b.py",
        )
        cmd.validate = MagicMock(
            return_value={"valid": False, "error": dup_err, "error_type": "duplicate"}
        )

        cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert any("Duplicate function name" in c for c in calls)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_load_error_calls_handler(self, mock_fire, tmp_path):
        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        load_err = UDFLoadError(module="bad", file="bad.py", error="SyntaxError")
        cmd.validate = MagicMock(
            return_value={"valid": False, "error": load_err, "error_type": "load_error"}
        )

        cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert any("Error loading UDF" in c for c in calls)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_not_found_error_calls_handler(self, mock_fire, tmp_path):
        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        nf_err = FunctionNotFoundError(
            "not found",
            context={"function_name": "missing_fn", "available_functions": ["other"]},
        )
        cmd.validate = MagicMock(
            return_value={"valid": False, "error": nf_err, "error_type": "not_found"}
        )

        with patch("agent_actions.validation.validate_udfs.get_udf_metadata") as mock_meta:
            mock_meta.return_value = {"file": "tools.py"}
            cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert any("'missing_fn' not found" in c for c in calls)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_unexpected_exception_raises_click_exception(self, mock_fire, tmp_path):
        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(side_effect=RuntimeError("boom"))

        with pytest.raises(click.ClickException):
            cmd.execute()

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_not_found_with_many_available_truncates(self, mock_fire, tmp_path):
        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        available = [f"func_{i}" for i in range(15)]
        nf_err = FunctionNotFoundError(
            "not found",
            context={"function_name": "missing", "available_functions": available},
        )
        cmd.validate = MagicMock(
            return_value={"valid": False, "error": nf_err, "error_type": "not_found"}
        )

        with patch("agent_actions.validation.validate_udfs.get_udf_metadata") as mock_meta:
            mock_meta.return_value = {"file": "tools.py"}
            cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        # Should show "... and N more"
        assert any("and 5 more" in c for c in calls)
