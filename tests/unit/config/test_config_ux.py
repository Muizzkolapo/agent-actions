"""Tests for config UX improvements: unknown defaults warning, fuzzy match, validation errors."""

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError
from agent_actions.validation.action_validators.unknown_keys_detector import UnknownKeysDetector

_WORKFLOW_HEADER = "name: test_workflow\ndescription: test workflow\nversion: '1.0'\n"

_ACTIONS_BLOCK = "actions:\n  - name: extract\n    intent: extract data\n    kind: llm\n"


def _make_manager(tmp_path, workflow_yaml):
    cfg = tmp_path / "workflow.yml"
    cfg.write_text(workflow_yaml)
    default = tmp_path / "default.yml"
    default.write_text("{}")
    (tmp_path / "templates").mkdir()
    cm = ConfigManager(str(cfg), str(default), project_root=tmp_path)
    cm.load_configs()
    return cm


def _call_get_user_agents(cm, tmp_path):
    with (
        patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
        patch("agent_actions.config.manager.load_project_config", return_value={}),
        patch(
            "agent_actions.output.response.expander.ActionExpander.expand_actions_to_agents",
            return_value={"test_workflow": [{"agent_type": "extract"}]},
        ),
    ):
        mock_pm_cls.return_value.get_project_root.return_value = tmp_path
        return cm.get_user_agents()


@pytest.fixture
def _enable_propagation():
    """Temporarily enable propagation on agent_actions logger so caplog captures records."""
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = original


class TestUnknownDefaultsKeysWarning:
    """Issue 1: Unknown keys in defaults config should produce a warning."""

    @pytest.mark.usefixtures("_enable_propagation")
    def test_unknown_defaults_key_logs_warning(self, tmp_path, caplog):
        """Typo like 'modle_name' in defaults triggers a warning."""
        cm = _make_manager(
            tmp_path,
            _WORKFLOW_HEADER
            + _ACTIONS_BLOCK
            + "defaults:\n  modle_name: gpt-4\n  model_vendor: openai\n",
        )
        with caplog.at_level(logging.WARNING):
            _call_get_user_agents(cm, tmp_path)

        assert any("Unknown keys in defaults config" in r.message for r in caplog.records)
        assert any("modle_name" in r.message for r in caplog.records)

    @pytest.mark.usefixtures("_enable_propagation")
    def test_no_warning_when_no_unknown_keys(self, tmp_path, caplog):
        """Valid defaults keys produce no warning."""
        cm = _make_manager(
            tmp_path,
            _WORKFLOW_HEADER
            + _ACTIONS_BLOCK
            + "defaults:\n  model_vendor: openai\n  model_name: gpt-4\n",
        )
        with caplog.at_level(logging.WARNING):
            _call_get_user_agents(cm, tmp_path)

        assert not any("Unknown keys in defaults config" in r.message for r in caplog.records)

    @pytest.mark.usefixtures("_enable_propagation")
    def test_no_warning_when_no_defaults(self, tmp_path, caplog):
        """No defaults section produces no warning."""
        cm = _make_manager(tmp_path, _WORKFLOW_HEADER + _ACTIONS_BLOCK)
        with caplog.at_level(logging.WARNING):
            _call_get_user_agents(cm, tmp_path)

        assert not any("Unknown keys in defaults config" in r.message for r in caplog.records)

    @pytest.mark.usefixtures("_enable_propagation")
    def test_warning_lists_known_keys(self, tmp_path, caplog):
        """Warning message includes the list of known keys for reference."""
        cm = _make_manager(
            tmp_path,
            _WORKFLOW_HEADER + _ACTIONS_BLOCK + "defaults:\n  bogus_key: value\n",
        )
        with caplog.at_level(logging.WARNING):
            _call_get_user_agents(cm, tmp_path)

        warning_msgs = [r.message for r in caplog.records if "Unknown keys" in r.message]
        assert len(warning_msgs) == 1
        assert "model_name" in warning_msgs[0]
        assert "model_vendor" in warning_msgs[0]


class TestFuzzyMatchSuggestions:
    """Issue 2: Unknown keys detector should suggest closest valid key."""

    def _make_context(self, entry):
        return SimpleNamespace(
            entry=entry,
            normalized_entry=entry,
            description="Action 'extract'",
        )

    def test_typo_gets_suggestion(self):
        """'modle_name' should suggest 'model_name'."""
        detector = UnknownKeysDetector()
        ctx = self._make_context({"agent_type": "llm", "modle_name": "gpt-4"})

        with patch(
            "agent_actions.validation.utils.action_config_validation_utilities."
            "ActionConfigValidationUtilities.get_all_known_action_keys",
            return_value={"agent_type", "model_name", "model_vendor", "kind", "intent", "name"},
        ):
            result = detector.validate(ctx)

        assert result.warnings
        assert "Did you mean" in result.warnings[0]
        assert "modle_name -> model_name" in result.warnings[0]

    def test_no_suggestion_for_distant_key(self):
        """A completely unrelated key should not get a suggestion."""
        detector = UnknownKeysDetector()
        ctx = self._make_context({"agent_type": "llm", "zzzzzzz": "value"})

        with patch(
            "agent_actions.validation.utils.action_config_validation_utilities."
            "ActionConfigValidationUtilities.get_all_known_action_keys",
            return_value={"agent_type", "model_name", "model_vendor", "kind"},
        ):
            result = detector.validate(ctx)

        assert result.warnings
        assert "Did you mean" not in result.warnings[0]
        assert "zzzzzzz" in result.warnings[0]

    def test_no_warnings_for_known_keys(self):
        """Known keys produce no warnings."""
        detector = UnknownKeysDetector()
        ctx = self._make_context({"agent_type": "llm", "model_name": "gpt-4"})

        with patch(
            "agent_actions.validation.utils.action_config_validation_utilities."
            "ActionConfigValidationUtilities.get_all_known_action_keys",
            return_value={"agent_type", "model_name", "model_vendor"},
        ):
            result = detector.validate(ctx)

        assert not result.warnings

    def test_multiple_typos_get_individual_suggestions(self):
        """Each typo key gets its own suggestion if close enough."""
        detector = UnknownKeysDetector()
        ctx = self._make_context(
            {
                "agent_type": "llm",
                "modle_name": "gpt-4",
                "modle_vendor": "openai",
            }
        )

        with patch(
            "agent_actions.validation.utils.action_config_validation_utilities."
            "ActionConfigValidationUtilities.get_all_known_action_keys",
            return_value={"agent_type", "model_name", "model_vendor", "kind"},
        ):
            result = detector.validate(ctx)

        assert result.warnings
        warning = result.warnings[0]
        assert "modle_name -> model_name" in warning
        assert "modle_vendor -> model_vendor" in warning


class TestValidationErrorSurfacing:
    """Issue 3: Pydantic field errors should be surfaced in ConfigurationError context."""

    def test_validation_error_includes_field_details(self, tmp_path):
        """ConfigurationError context should include structured validation_errors."""
        cm = _make_manager(
            tmp_path,
            _WORKFLOW_HEADER + "actions:\n  - invalid_entry: true\n",
        )

        with (
            patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
            patch("agent_actions.config.manager.load_project_config", return_value={}),
            pytest.raises(ConfigurationError) as exc_info,
        ):
            mock_pm_cls.return_value.get_project_root.return_value = tmp_path
            cm.get_user_agents()

        err = exc_info.value
        assert "validation_errors" in err.context
        field_errors = err.context["validation_errors"]
        assert isinstance(field_errors, list)
        assert len(field_errors) > 0
        first = field_errors[0]
        assert "field" in first
        assert "message" in first
        assert "type" in first

    def test_validation_error_capped_at_10(self, tmp_path):
        """At most 10 validation errors are included in context."""
        cm = _make_manager(
            tmp_path,
            _WORKFLOW_HEADER
            + "actions:\n  - name: extract\n    intent: extract data\n    kind: llm\n    dependencies: not_a_list\n",
        )

        with (
            patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
            patch("agent_actions.config.manager.load_project_config", return_value={}),
            pytest.raises(ConfigurationError) as exc_info,
        ):
            mock_pm_cls.return_value.get_project_root.return_value = tmp_path
            cm.get_user_agents()

        err = exc_info.value
        assert "validation_errors" in err.context
        assert len(err.context["validation_errors"]) <= 10

    def test_validation_error_preserves_config_path_and_workflow_name(self, tmp_path):
        """config_path and workflow_name are still in context alongside validation_errors."""
        cm = _make_manager(
            tmp_path,
            "name: my_workflow\ndescription: test\nversion: '1.0'\nactions:\n  - invalid_entry: true\n",
        )

        with (
            patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
            patch("agent_actions.config.manager.load_project_config", return_value={}),
            pytest.raises(ConfigurationError) as exc_info,
        ):
            mock_pm_cls.return_value.get_project_root.return_value = tmp_path
            cm.get_user_agents()

        err = exc_info.value
        assert "config_path" in err.context
        assert "workflow_name" in err.context
        assert err.context["workflow_name"] == "my_workflow"
