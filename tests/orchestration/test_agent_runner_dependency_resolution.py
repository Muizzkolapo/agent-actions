"""
Tests for _resolve_dependency_directories() in AgentRunner.

Tests the simplified dependency model where:
- `dependencies` = input sources only
- Context sources are auto-inferred from context_scope
- Backward compatibility with deprecated primary_dependency
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import shutil

from agent_actions.orchestration.agent_runner import AgentRunner
from agent_actions.errors import DependencyError


class TestResolveDependencyDirectories:
    """Test _resolve_dependency_directories() method."""

    @pytest.fixture
    def agent_runner(self):
        """Create AgentRunner instance with mocked dependencies."""
        runner = AgentRunner.__new__(AgentRunner)
        runner.agent_indices = {"action_A": 0, "action_B": 1, "action_C": 2}
        runner.manifest_manager = None  # No manifest manager for simple tests
        return runner

    @pytest.fixture
    def temp_agent_folder(self):
        """Create temporary agent folder with target directories."""
        temp_dir = Path(tempfile.mkdtemp())
        target_dir = temp_dir / "target"
        target_dir.mkdir(parents=True)

        # Create dependency directories
        (target_dir / "action_A").mkdir()
        (target_dir / "action_B").mkdir()
        (target_dir / "action_C").mkdir()

        yield temp_dir

        # Cleanup
        shutil.rmtree(temp_dir)

    def test_single_dependency_returns_single_directory(self, agent_runner, temp_agent_folder):
        """Test single dependency returns its directory."""
        dependencies = ["action_A"]
        agent_config = {"dependencies": dependencies}

        result = agent_runner._resolve_dependency_directories(
            temp_agent_folder, dependencies, agent_config, "test_action"
        )

        assert len(result) == 1
        assert result[0] == temp_agent_folder / "target" / "action_A"

    def test_multiple_dependencies_returns_all_directories(self, agent_runner, temp_agent_folder):
        """Test multiple dependencies returns all directories (for merging)."""
        dependencies = ["action_A", "action_B", "action_C"]
        agent_config = {"dependencies": dependencies}

        result = agent_runner._resolve_dependency_directories(
            temp_agent_folder, dependencies, agent_config, "test_action"
        )

        assert len(result) == 3
        assert temp_agent_folder / "target" / "action_A" in result
        assert temp_agent_folder / "target" / "action_B" in result
        assert temp_agent_folder / "target" / "action_C" in result

    def test_missing_dependency_raises_error(self, agent_runner, temp_agent_folder):
        """Test that missing dependency raises DependencyError."""
        dependencies = ["action_A", "nonexistent_action"]
        agent_config = {"dependencies": dependencies}

        with pytest.raises(DependencyError) as exc_info:
            agent_runner._resolve_dependency_directories(
                temp_agent_folder, dependencies, agent_config, "test_action"
            )

        assert "nonexistent_action" in str(exc_info.value)
        assert "not found" in str(exc_info.value)

    def test_deprecated_primary_dependency_uses_primary_only(self, agent_runner, temp_agent_folder):
        """Test deprecated primary_dependency falls back to primary only."""
        dependencies = ["action_A", "action_B", "action_C"]
        agent_config = {
            "dependencies": dependencies,
            "primary_dependency": "action_B",  # Deprecated field
        }

        with patch("agent_actions.orchestration.agent_runner.logger") as mock_logger:
            result = agent_runner._resolve_dependency_directories(
                temp_agent_folder, dependencies, agent_config, "test_action"
            )

            # Should log deprecation warning
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "DEPRECATION WARNING" in warning_msg
            assert "primary_dependency" in warning_msg

        # Should only return primary dependency directory (backward compat)
        assert len(result) == 1
        assert result[0] == temp_agent_folder / "target" / "action_B"

    def test_empty_dependencies_returns_empty_list(self, agent_runner, temp_agent_folder):
        """Test empty dependencies returns empty list."""
        dependencies = []
        agent_config = {"dependencies": dependencies}

        result = agent_runner._resolve_dependency_directories(
            temp_agent_folder, dependencies, agent_config, "test_action"
        )

        assert result == []


class TestResolveDependencyDirectoriesIntegration:
    """Integration tests for dependency resolution with real workflow patterns."""

    @pytest.fixture
    def temp_workflow_folder(self):
        """Create temporary folder mimicking real workflow structure."""
        temp_dir = Path(tempfile.mkdtemp())
        target_dir = temp_dir / "target"
        target_dir.mkdir(parents=True)

        # Create quiz generation workflow directories
        actions = [
            "extract_raw_qa",
            "flatten_raw_questions",
            "classify_question_type",
            "get_authoring_prompt",
            "write_scenario_question",
            "fix_options_format",
            "suggest_distractor_counts",
            "add_answer_text",
            "generate_distractor_1",
        ]
        for action in actions:
            (target_dir / action).mkdir()

        yield temp_dir

        shutil.rmtree(temp_dir)

    @pytest.fixture
    def agent_runner_with_workflow(self, temp_workflow_folder):
        """Create AgentRunner with workflow indices."""
        runner = AgentRunner.__new__(AgentRunner)
        runner.agent_indices = {
            "extract_raw_qa": 0,
            "flatten_raw_questions": 1,
            "classify_question_type": 2,
            "get_authoring_prompt": 3,
            "write_scenario_question": 4,
            "fix_options_format": 5,
            "suggest_distractor_counts": 6,
            "add_answer_text": 7,
            "generate_distractor_1": 8,
        }
        runner.manifest_manager = None  # No manifest manager for simple tests
        return runner

    def test_generate_distractor_pattern_single_input(
        self, agent_runner_with_workflow, temp_workflow_folder
    ):
        """Test generate_distractor_1 pattern: single input source.

        In new model:
        - dependencies: add_answer_text (single input)
        - Context deps (suggest_distractor_counts, write_scenario_question) auto-inferred
        """
        dependencies = ["add_answer_text"]  # Only input source
        agent_config = {"dependencies": dependencies}

        result = agent_runner_with_workflow._resolve_dependency_directories(
            temp_workflow_folder, dependencies, agent_config, "generate_distractor_1"
        )

        # Should only return add_answer_text directory
        assert len(result) == 1
        assert result[0] == temp_workflow_folder / "target" / "add_answer_text"

    def test_aggregate_votes_pattern_multiple_inputs(
        self, agent_runner_with_workflow, temp_workflow_folder
    ):
        """Test aggregate pattern: multiple input sources for merging.

        Pattern: dependencies: [validate_1, validate_2, validate_3]
        All are input sources to be merged by reduce_key.
        """
        # Create validate directories
        for i in range(1, 4):
            (temp_workflow_folder / "target" / f"validate_{i}").mkdir()

        runner = AgentRunner.__new__(AgentRunner)
        runner.agent_indices = {"validate_1": 0, "validate_2": 1, "validate_3": 2, "aggregate": 3}
        runner.manifest_manager = None

        dependencies = ["validate_1", "validate_2", "validate_3"]
        agent_config = {"dependencies": dependencies, "reduce_key": "parent_id"}

        result = runner._resolve_dependency_directories(
            temp_workflow_folder, dependencies, agent_config, "aggregate"
        )

        # Should return all 3 directories for merging
        assert len(result) == 3

    def test_write_scenario_question_pattern_single_input(
        self, agent_runner_with_workflow, temp_workflow_folder
    ):
        """Test write_scenario_question pattern after migration.

        Old: dependencies: [get_authoring_prompt, flatten_raw_questions, classify_question_type]
        New: dependencies: get_authoring_prompt (single input)
        Context deps (flatten_raw_questions, classify_question_type) auto-inferred from context_scope.
        """
        dependencies = ["get_authoring_prompt"]  # Single input after migration
        agent_config = {
            "dependencies": dependencies,
            "context_scope": {
                "observe": [
                    "flatten_raw_questions.question_text",
                    "classify_question_type.quiz_type",
                    "get_authoring_prompt.authoring_prompt",
                ]
            },
        }

        result = agent_runner_with_workflow._resolve_dependency_directories(
            temp_workflow_folder, dependencies, agent_config, "write_scenario_question"
        )

        # Should only return get_authoring_prompt directory (input source)
        # Context deps are NOT returned here - they're loaded via historical loader
        assert len(result) == 1
        assert result[0] == temp_workflow_folder / "target" / "get_authoring_prompt"
