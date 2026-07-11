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
        # Pipeline enrichment is in-place on the returned exception object —
        # assert it directly so the formatter contract stays observable from
        # tests, not just from rendered CLI output.
        err = result["error"]
        assert err.context["pipeline_stage"] == "validate_udfs"
        assert err.context["search_path"] == str(Path(str(tmp_path)).resolve())
        assert err.context["requested_path"] == str(tmp_path)

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

        with pytest.raises(click.exceptions.Exit):
            cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert any("Duplicate function name" in c for c in calls)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_load_error_routes_through_shared_formatter(self, mock_fire, tmp_path):
        """Delegates to format_user_error → UDFLoadErrorFormatter so the
        validate-udfs UX stays in sync with the rest of the CLI."""
        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        load_err = UDFLoadError(module="bad", file="bad.py", error="SyntaxError")
        cmd.validate = MagicMock(
            return_value={"valid": False, "error": load_err, "error_type": "load_error"}
        )

        with pytest.raises(click.exceptions.Exit):
            cmd.execute()

        joined = "\n".join(str(c) for c in cmd.console.print.call_args_list)
        # Marker line + canonical formatter output.
        assert "UDF load failed" in joined
        assert "Failed to load UDF module 'bad'" in joined
        assert "Python could not import the UDF module: SyntaxError" in joined
        assert "File: bad.py" in joined

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_discovery_sentinel_renders_directory_error_not_module_error(self, mock_fire, tmp_path):
        """When discover_udfs signals the user-code dir is missing/invalid via
        UDFLoadError.DISCOVERY_SENTINEL, the handler must render a directory-
        appropriate message and never leak the sentinel string to the user."""
        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        load_err = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file="/no/such/dir",
            error="User code directory not found",
        )
        cmd.validate = MagicMock(
            return_value={"valid": False, "error": load_err, "error_type": "load_error"}
        )

        with pytest.raises(click.exceptions.Exit):
            cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        joined = "\n".join(calls)
        assert "UDF discovery failed" in joined
        assert "/no/such/dir" in joined
        assert "User code directory not found" in joined
        assert UDFLoadError.DISCOVERY_SENTINEL not in joined
        # Directory-fix wording, not import-error wording.
        assert "user-code directory" in joined or "tool_path" in joined

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

        with (
            patch("agent_actions.validation.validate_udfs.get_udf_metadata") as mock_meta,
            pytest.raises(click.exceptions.Exit),
        ):
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

        with (
            patch("agent_actions.validation.validate_udfs.get_udf_metadata") as mock_meta,
            pytest.raises(click.exceptions.Exit),
        ):
            mock_meta.return_value = {"file": "tools.py"}
            cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        # Should show "... and 5 more"
        assert any("and 5 more" in c for c in calls)


# ---------------------------------------------------------------------------
# Unknown bus-namespace warnings (UDF reads data.get("X") for an unknown X)
# ---------------------------------------------------------------------------


class TestBusNamespaceWarnings:
    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        from agent_actions.utils.udf_management.registry import clear_registry

        clear_registry()
        yield
        clear_registry()

    def _discover(self, tool_dir: Path, body: str):
        """Write an isolated tool file and register it via real discovery."""
        from agent_actions.input.loaders.udf import discover_udfs

        tool_dir.mkdir()
        (tool_dir / "agg.py").write_text(
            "from agent_actions import udf_tool\n\n@udf_tool\ndef aggregate(data):\n" + body
        )
        return discover_udfs(tool_dir)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_unknown_bus_namespace_warns_and_exits_zero(self, mock_fire, tmp_path):
        registry = self._discover(tmp_path / "tools", "    return data.get('typo_action_name')\n")

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": registry,
                "impl_refs": set(),
                "action_names": {"real_action"},
            }
        )

        cmd.execute()  # warning, not error: must not raise

        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert any("typo_action_name" in c and "aggregate" in c for c in calls)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_action_and_framework_namespaces_are_not_flagged(self, mock_fire, tmp_path):
        # One file mixing a known action name, a framework namespace, and a typo:
        # only the typo must be flagged (proves the scan runs AND discriminates).
        registry = self._discover(
            tmp_path / "tools",
            "    a = data.get('real_action')\n"
            "    b = data['seed']\n"
            "    c = data.get('typo_name')\n"
            "    return {}\n",
        )

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": registry,
                "impl_refs": set(),
                "action_names": {"real_action"},
            }
        )

        cmd.execute()

        joined = " ".join(str(c) for c in cmd.console.print.call_args_list)
        assert "typo_name" in joined
        assert "real_action" not in joined
        assert "'seed'" not in joined
