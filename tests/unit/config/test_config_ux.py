"""Tests for config UX: undeclared defaults keys, fuzzy match, validation errors."""

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


class TestAnUndeclaredDefaultsKey:
    """A key the schema does not declare stops the load rather than being dropped."""

    def _refusal(self, tmp_path, defaults: str) -> str:
        cm = _make_manager(tmp_path, _WORKFLOW_HEADER + _ACTIONS_BLOCK + defaults)
        with pytest.raises(ConfigurationError) as excinfo:
            _call_get_user_agents(cm, tmp_path)
        return " ".join(e["message"] for e in excinfo.value.context["validation_errors"])

    def test_a_mistyped_key_names_the_key_it_resembles(self, tmp_path):
        message = self._refusal(
            tmp_path, "defaults:\n  modle_name: gpt-4\n  model_vendor: openai\n"
        )

        assert "did you mean 'model_name'?" in message

    def test_a_key_resembling_nothing_names_the_keys_the_block_takes(self, tmp_path):
        message = self._refusal(tmp_path, "defaults:\n  bogus_key: value\n")

        assert "bogus_key" in message
        assert "model_name" in message and "model_vendor" in message

    def test_declared_keys_do_not_refuse_the_load(self, tmp_path):
        cm = _make_manager(
            tmp_path,
            _WORKFLOW_HEADER
            + _ACTIONS_BLOCK
            + "defaults:\n  model_vendor: openai\n  model_name: gpt-4\n",
        )

        assert _call_get_user_agents(cm, tmp_path) == [{"agent_type": "extract"}]

    def test_no_defaults_block_does_not_refuse_the_load(self, tmp_path):
        cm = _make_manager(tmp_path, _WORKFLOW_HEADER + _ACTIONS_BLOCK)

        assert _call_get_user_agents(cm, tmp_path) == [{"agent_type": "extract"}]


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
