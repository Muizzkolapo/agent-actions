"""Tests for ValidateUDFsCommand — UDF validation without running workflows."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from rich.console import Console

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


class TestExtractActionNames:
    def _make_cmd(self) -> ValidateUDFsCommand:
        return ValidateUDFsCommand.__new__(ValidateUDFsCommand)

    def test_list_of_action_dicts(self):
        cmd = self._make_cmd()
        config = {"name": "wf", "actions": [{"name": "split"}, {"name": "score"}]}
        assert cmd._extract_action_names(config) == {"split", "score"}

    def test_no_actions_key(self):
        cmd = self._make_cmd()
        assert cmd._extract_action_names({}) == set()

    def test_non_list_actions_is_safe(self):
        # Legacy/malformed shapes must degrade to empty, never raise.
        cmd = self._make_cmd()
        assert cmd._extract_action_names({"actions": {"s": {"impl": "f"}}}) == set()

    def test_action_without_name_is_skipped(self):
        cmd = self._make_cmd()
        config = {"actions": [{"name": "ok"}, {"impl": "no_name"}, "bare_string"]}
        assert cmd._extract_action_names(config) == {"ok"}


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
                "action_names": set(),
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
        import sys

        from agent_actions.utils.module_loader import clear_module_cache
        from agent_actions.utils.udf_management.registry import clear_registry

        def _reset():
            clear_registry()
            clear_module_cache()
            # clear_registry/clear_module_cache do NOT evict the sys.modules entries
            # discover_udfs creates under the "agent_actions._udfs." prefix; without
            # this, a second discover of the same file stem returns a stale (empty)
            # module and the test silently scans nothing.
            for name in [k for k in sys.modules if k.startswith("agent_actions._udfs.")]:
                sys.modules.pop(name, None)

        _reset()
        yield
        _reset()

    def _discover(self, tool_dir: Path, mod: str, body: str):
        """Write an isolated tool file and register it via real discovery."""
        from agent_actions.input.loaders.udf import discover_udfs

        tool_dir.mkdir()
        (tool_dir / f"{mod}.py").write_text(
            "from agent_actions import udf_tool\n\n@udf_tool\ndef aggregate(data):\n" + body
        )
        return discover_udfs(tool_dir)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_unknown_bus_namespace_warns_and_exits_zero(self, mock_fire, tmp_path):
        registry = self._discover(
            tmp_path / "tools", "tool_unknown", "    return data.get('typo_action_name')\n"
        )

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": registry,
                "impl_refs": {"aggregate"},
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
            "tool_mixed",
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
                "impl_refs": {"aggregate"},
                "action_names": {"real_action"},
            }
        )

        cmd.execute()

        joined = " ".join(str(c) for c in cmd.console.print.call_args_list)
        assert "typo_name" in joined
        assert "real_action" not in joined
        assert "'seed'" not in joined

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_unreferenced_udf_in_shared_dir_is_not_scanned(self, mock_fire, tmp_path):
        # A shared tools/ dir holds UDFs for several workflows. A UDF this workflow
        # does NOT reference reads its own workflow's namespace — it must not be
        # flagged against this workflow's action names (the real-project failure).
        from agent_actions.input.loaders.udf import discover_udfs

        tool_dir = tmp_path / "tools"
        tool_dir.mkdir()
        (tool_dir / "used.py").write_text(
            "from agent_actions import udf_tool\n\n@udf_tool\ndef used_tool(data):\n"
            "    return data.get('used_typo')\n"
        )
        (tool_dir / "other.py").write_text(
            "from agent_actions import udf_tool\n\n@udf_tool\ndef other_tool(data):\n"
            "    return data.get('some_other_workflow_ns')\n"
        )
        registry = discover_udfs(tool_dir)

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": registry,
                "impl_refs": {"used_tool"},
                "action_names": {"real_action"},
            }
        )

        cmd.execute()

        joined = " ".join(str(c) for c in cmd.console.print.call_args_list)
        # Positive (non-vacuous): the referenced UDF's own typo IS flagged...
        assert "used_typo" in joined
        # ...while the unreferenced tool's read is not scanned at all.
        assert "some_other_workflow_ns" not in joined
        assert "other_tool" not in joined

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_record_helper_in_referenced_file_is_not_scanned(self, mock_fire, tmp_path):
        # A referenced UDF's file also defines a plain helper that receives a record
        # (not the action bus) and reads record fields. Only the registered UDF's own
        # body is scoped, so the helper's field reads must not warn.
        from agent_actions.input.loaders.udf import discover_udfs

        tool_dir = tmp_path / "tools"
        tool_dir.mkdir()
        # The helper's `data` is a record passed by used_tool, not the action bus;
        # a whole-file scan would wrongly flag `question` against the bus namespaces.
        (tool_dir / "used.py").write_text(
            "from agent_actions import udf_tool\n\n"
            "def _process_record(data):\n    return data.get('question')\n\n"
            "@udf_tool\ndef used_tool(data):\n    return data.get('used_typo')\n"
        )
        registry = discover_udfs(tool_dir)

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": registry,
                "impl_refs": {"used_tool"},
                "action_names": {"real_action"},
            }
        )

        cmd.execute()

        joined = " ".join(str(c) for c in cmd.console.print.call_args_list)
        # Positive (non-vacuous): the registered UDF's own typo IS flagged...
        assert "used_typo" in joined
        # ...while the same-file helper's record-field read is not scanned.
        assert "question" not in joined
        assert "_process_record" not in joined

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_reserved_config_token_is_flagged(self, mock_fire, tmp_path):
        # prompt/schema/action are reserved config tokens, NOT runtime bus keys, so a
        # UDF reading data.get("schema") silently gets {} — it must be flagged (they
        # are deliberately excluded from the valid runtime-bus set).
        registry = self._discover(
            tmp_path / "tools", "tool_reserved", "    return data.get('schema')\n"
        )

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": registry,
                "impl_refs": {"aggregate"},
                "action_names": {"real_action"},
            }
        )

        cmd.execute()

        joined = " ".join(str(c) for c in cmd.console.print.call_args_list)
        assert "bus namespace 'schema'" in joined

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_framework_namespaces_are_not_flagged(self, mock_fire, tmp_path):
        # The four real framework bus keys must never be flagged.
        registry = self._discover(
            tmp_path / "tools",
            "tool_framework",
            "    return (data.get('source'), data['version'], data.get('workflow'), data['seed'])\n",
        )

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": registry,
                "impl_refs": {"aggregate"},
                "action_names": {"real_action"},
            }
        )

        cmd.execute()

        joined = " ".join(str(c) for c in cmd.console.print.call_args_list)
        assert "bus namespace" not in joined

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_bracketed_bus_key_does_not_crash(self, mock_fire, tmp_path):
        # A bus-key literal containing Rich markup must not crash the console or drop
        # the offending key — the warning text is escaped before printing.
        registry = self._discover(
            tmp_path / "tools", "tool_markup", "    return data.get('[/x]y')\n"
        )

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = Console()  # real console, markup enabled — would MarkupError unescaped
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": registry,
                "impl_refs": {"aggregate"},
                "action_names": {"real_action"},
            }
        )

        with cmd.console.capture() as cap:
            cmd.execute()  # must not raise

        assert "[/x]y" in cap.get()


# ---------------------------------------------------------------------------
# FILE-mode UDF return-contract warnings
# ---------------------------------------------------------------------------


class TestFileUdfContractWarnings:
    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        from agent_actions.utils.udf_management.registry import clear_registry

        clear_registry()
        yield
        clear_registry()

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_file_udf_returning_list_prints_warning_and_succeeds(self, mock_fire, tmp_path):
        from agent_actions.config.types import Granularity
        from agent_actions.utils.udf_management.registry import UDF_REGISTRY, udf_tool

        @udf_tool(granularity=Granularity.FILE)
        def dedup_scores(data) -> list[dict]:
            return data

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": dict(UDF_REGISTRY),
                "impl_refs": {"dedup_scores"},
                "action_names": set(),
            }
        )

        cmd.execute()  # warning, not error: must not raise

        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert any("dedup_scores" in c and "FileUDFResult" in c for c in calls)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_file_udf_not_referenced_by_workflow_is_not_warned(self, mock_fire, tmp_path):
        # A mis-annotated FILE UDF this workflow never calls cannot crash its run,
        # so validate-udfs -a <workflow> must not warn about it.
        from agent_actions.config.types import Granularity
        from agent_actions.utils.udf_management.registry import UDF_REGISTRY, udf_tool

        @udf_tool(granularity=Granularity.FILE)
        def other_workflows_udf(data) -> list[dict]:
            return data

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": dict(UDF_REGISTRY),
                "impl_refs": {"unrelated"},
                "action_names": set(),
            }
        )

        cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert not any("other_workflows_udf" in c for c in calls)

    @patch("agent_actions.validation.validate_udfs.fire_event")
    def test_file_udf_returning_fileudfresult_prints_no_warning(self, mock_fire, tmp_path):
        from agent_actions.config.types import Granularity
        from agent_actions.utils.udf_management.registry import (
            UDF_REGISTRY,
            FileUDFResult,
            udf_tool,
        )

        @udf_tool(granularity=Granularity.FILE)
        def merge_scores(data) -> FileUDFResult:
            return FileUDFResult(outputs=[])

        cmd = ValidateUDFsCommand("agent.yml", str(tmp_path))
        cmd.console = MagicMock()
        # Reference merge_scores so the annotation is actually inspected — with an
        # empty impl_refs the scope filter would skip it before the matcher runs.
        cmd.validate = MagicMock(
            return_value={
                "valid": True,
                "registry": dict(UDF_REGISTRY),
                "impl_refs": {"merge_scores"},
                "action_names": set(),
            }
        )

        cmd.execute()

        calls = [str(c) for c in cmd.console.print.call_args_list]
        assert not any("merge_scores" in c and "FileUDFResult" in c for c in calls)
