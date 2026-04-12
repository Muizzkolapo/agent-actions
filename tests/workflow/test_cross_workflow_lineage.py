"""Tests for cross-workflow first action strategy selection and lineage preservation.

When an action has only cross-workflow dependencies (dict syntax stripped by Pydantic),
the runner must classify it as intermediate (StandardStrategy), not initial.
InitialStrategy would set is_first_stage=True, causing source_guid regeneration
and lineage truncation.

Regression tests for: specs/new/038-cross-workflow-first-action-lineage-fix.md
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.di.container import ProcessorFactory
from agent_actions.workflow.config_pipeline import load_workflow_configs
from agent_actions.workflow.runner import ActionRunner


@pytest.fixture()
def runner():
    factory = MagicMock(spec=ProcessorFactory)
    return ActionRunner(use_tools=True, processor_factory=factory)


def _run_config_pipeline(raw_actions, parsed_configs):
    """Build mocked config pipeline and run load_workflow_configs.

    Args:
        raw_actions: List of raw YAML action dicts (pre-Pydantic).
        parsed_configs: Dict of action_name → parsed config dict (post-Pydantic).
    """
    manager = MagicMock()
    manager.agent_name = "test_wf"
    manager.execution_order = list(parsed_configs.keys())
    manager.child_pipeline = None
    manager.user_config = {"actions": raw_actions}
    manager.get_all_agent_configs_as_dicts.return_value = parsed_configs

    config = MagicMock()
    config.manager = manager
    config.paths.constructor_path = "/fake/path.yml"
    config.project_root = None

    return load_workflow_configs(config, MagicMock())


class TestCrossWorkflowStrategySelection:
    """Strategy selection must account for cross-workflow deps stripped by Pydantic."""

    @patch.object(ActionRunner, "process_and_generate_for_action")
    def test_cross_workflow_only_uses_intermediate_strategy(self, mock_pga, runner):
        """Action with only cross-workflow deps (stripped) should use intermediate strategy."""
        mock_pga.return_value = "/output"
        config = {
            "agent_type": "consumer",
            "dependencies": [],
            "_has_cross_workflow_deps": True,
        }
        runner.run_action(config, "consumer", None, 0)
        call_params = mock_pga.call_args[0][0]
        assert call_params.strategy is runner.strategies["intermediate"]

    @patch.object(ActionRunner, "process_and_generate_for_action")
    def test_mixed_local_and_cross_workflow_uses_intermediate(self, mock_pga, runner):
        """Action with both local and cross-workflow deps uses intermediate."""
        mock_pga.return_value = "/output"
        config = {
            "agent_type": "consumer",
            "dependencies": ["local_action"],
            "_has_cross_workflow_deps": True,
        }
        runner.run_action(config, "consumer", None, 0)
        call_params = mock_pga.call_args[0][0]
        assert call_params.strategy is runner.strategies["intermediate"]

    @patch.object(ActionRunner, "process_and_generate_for_action")
    def test_true_first_action_still_uses_initial(self, mock_pga, runner):
        """Action with no deps at all still uses initial strategy (regression guard)."""
        mock_pga.return_value = "/output"
        config = {"agent_type": "first_action"}
        runner.run_action(config, "first_action", None, 0)
        call_params = mock_pga.call_args[0][0]
        assert call_params.strategy is runner.strategies["initial"]

    @patch.object(ActionRunner, "process_and_generate_for_action")
    def test_no_flag_empty_deps_uses_initial(self, mock_pga, runner):
        """Without _has_cross_workflow_deps flag, empty deps -> initial (backward compat)."""
        mock_pga.return_value = "/output"
        config = {"agent_type": "action", "dependencies": []}
        runner.run_action(config, "action", None, 0)
        call_params = mock_pga.call_args[0][0]
        assert call_params.strategy is runner.strategies["initial"]

    @patch.object(ActionRunner, "process_and_generate_for_action")
    def test_flag_false_empty_deps_uses_initial(self, mock_pga, runner):
        """Explicit _has_cross_workflow_deps=False with empty deps -> initial."""
        mock_pga.return_value = "/output"
        config = {
            "agent_type": "action",
            "dependencies": [],
            "_has_cross_workflow_deps": False,
        }
        runner.run_action(config, "action", None, 0)
        call_params = mock_pga.call_args[0][0]
        assert call_params.strategy is runner.strategies["initial"]


class TestConfigPipelineCrossWorkflowFlag:
    """Config pipeline marks actions with cross-workflow deps."""

    def test_dict_dep_sets_flag(self):
        """Action with dict dep in raw YAML gets _has_cross_workflow_deps=True."""
        result = _run_config_pipeline(
            raw_actions=[
                {
                    "name": "consumer",
                    "dependencies": [
                        {"workflow": "upstream_wf", "action": "producer"},
                    ],
                },
            ],
            parsed_configs={"consumer": {"name": "consumer", "dependencies": []}},
        )
        assert result.action_configs["consumer"].get("_has_cross_workflow_deps") is True

    def test_string_only_deps_no_flag(self):
        """Action with only string deps does NOT get the flag."""
        result = _run_config_pipeline(
            raw_actions=[
                {"name": "processor", "dependencies": ["extractor"]},
            ],
            parsed_configs={"processor": {"name": "processor", "dependencies": ["extractor"]}},
        )
        assert "_has_cross_workflow_deps" not in result.action_configs["processor"]

    def test_no_deps_no_flag(self):
        """Action with no dependencies does NOT get the flag."""
        result = _run_config_pipeline(
            raw_actions=[{"name": "starter"}],
            parsed_configs={"starter": {"name": "starter"}},
        )
        assert "_has_cross_workflow_deps" not in result.action_configs["starter"]

    def test_mixed_deps_sets_flag(self):
        """Action with both string and dict deps gets _has_cross_workflow_deps=True."""
        result = _run_config_pipeline(
            raw_actions=[
                {
                    "name": "consumer",
                    "dependencies": [
                        "local_action",
                        {"workflow": "other_wf", "action": "remote"},
                    ],
                },
            ],
            parsed_configs={"consumer": {"name": "consumer", "dependencies": ["local_action"]}},
        )
        assert result.action_configs["consumer"].get("_has_cross_workflow_deps") is True
