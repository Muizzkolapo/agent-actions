"""Regression tests for agent_actions.prompt.service."""

import pytest

from agent_actions.prompt.service import PromptPreparationService


class TestDetermineStaticDataDir:
    """Tests for PromptPreparationService._determine_static_data_dir (G-4 regression)."""

    def test_none_workflow_config_path_raises_static_data_load_error(self):
        """G-4: workflow_seed_dir must be None-inited; no NameError when workflow_config_path is None."""
        from agent_actions.prompt.context.static_loader import StaticDataLoadError

        # Before the fix, `"workflow_seed_dir" in locals()` could mask a NameError if the
        # variable was never bound. After the fix, workflow_seed_dir = None is set up-front,
        # so this code path must reach StaticDataLoadError, not NameError.
        with pytest.raises(StaticDataLoadError):
            PromptPreparationService._determine_static_data_dir(None)

    def test_nonexistent_workflow_config_path_raises_static_data_load_error(self, tmp_path):
        """When workflow_config_path points to a directory without seed_data/, raise StaticDataLoadError."""
        from agent_actions.prompt.context.static_loader import StaticDataLoadError

        config_path = str(tmp_path / "workflow" / "agent_config" / "workflow.yml")
        (tmp_path / "workflow" / "agent_config").mkdir(parents=True)

        with pytest.raises(StaticDataLoadError):
            PromptPreparationService._determine_static_data_dir(config_path)

    def test_no_name_error_when_workflow_config_path_is_none(self):
        """G-4: workflow_seed_dir = None init prevents NameError; must raise StaticDataLoadError, not NameError."""
        from agent_actions.prompt.context.static_loader import StaticDataLoadError

        # The old locals() pattern would raise NameError if the branch never ran.
        # With explicit None-init the code must reach StaticDataLoadError cleanly.
        try:
            PromptPreparationService._determine_static_data_dir(None)
        except StaticDataLoadError:
            pass  # expected
        except NameError as exc:
            pytest.fail(f"locals() anti-pattern still present — got NameError: {exc}")
