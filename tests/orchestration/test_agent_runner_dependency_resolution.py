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

from agent_actions.workflow.runner import AgentRunner
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


class TestStrategySelectionByDependencies:
    """Test that strategy selection is based on dependencies, not position index.

    This ensures loop iterations of first-stage actions all use InitialStrategy
    to generate consistent source_guid values.
    """

    @pytest.fixture
    def mock_process_and_generate(self):
        """Mock process_and_generate_for_agent to capture strategy selection."""
        return MagicMock(return_value="/fake/output")

    def test_action_without_dependencies_uses_initial_strategy(self, mock_process_and_generate):
        """Actions without dependencies should use InitialStrategy regardless of idx."""
        runner = AgentRunner.__new__(AgentRunner)
        runner.process_and_generate_for_agent = mock_process_and_generate
        runner.strategies = {
            "initial": MagicMock(name="InitialStrategy"),
            "intermediate": MagicMock(name="StandardStrategy"),
        }

        # Call with idx=5 but no dependencies - should still use initial
        agent_config = {"agent_type": "test_action", "dependencies": []}
        runner.run_agent(
            agent_config=agent_config,
            agent_name="test_action",
            previous_agent_type=None,
            idx=5,  # Non-zero index
        )

        # Verify initial strategy was used
        call_args = mock_process_and_generate.call_args
        assert call_args is not None
        params = call_args[0][0]
        assert params.strategy == runner.strategies["initial"]

    def test_action_with_dependencies_uses_intermediate_strategy(self, mock_process_and_generate):
        """Actions with dependencies should use StandardStrategy."""
        runner = AgentRunner.__new__(AgentRunner)
        runner.process_and_generate_for_agent = mock_process_and_generate
        runner.strategies = {
            "initial": MagicMock(name="InitialStrategy"),
            "intermediate": MagicMock(name="StandardStrategy"),
        }

        # Call with idx=0 but HAS dependencies - should use intermediate
        agent_config = {
            "agent_type": "downstream_action",
            "dependencies": ["upstream_action"],
        }
        runner.run_agent(
            agent_config=agent_config,
            agent_name="downstream_action",
            previous_agent_type="upstream_action",
            idx=0,  # Zero index but has dependencies
        )

        # Verify intermediate strategy was used
        call_args = mock_process_and_generate.call_args
        assert call_args is not None
        params = call_args[0][0]
        assert params.strategy == runner.strategies["intermediate"]

    def test_version_numbers_all_use_initial_strategy(self, mock_process_and_generate):
        """All loop iterations without dependencies should use InitialStrategy.

        This is the key fix: extract_raw_qa_1, extract_raw_qa_2, extract_raw_qa_3
        should ALL use InitialStrategy to generate consistent source_guid.
        """
        runner = AgentRunner.__new__(AgentRunner)
        runner.process_and_generate_for_agent = mock_process_and_generate
        runner.strategies = {
            "initial": MagicMock(name="InitialStrategy"),
            "intermediate": MagicMock(name="StandardStrategy"),
        }

        # Simulate 3 loop iterations, all without dependencies
        version_numbers = [
            {
                "agent_type": "extract_raw_qa_1",
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "dependencies": [],
            },
            {
                "agent_type": "extract_raw_qa_2",
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "dependencies": [],
            },
            {
                "agent_type": "extract_raw_qa_3",
                "is_versioned_agent": True,
                "version_base_name": "extract_raw_qa",
                "dependencies": [],
            },
        ]

        for idx, config in enumerate(version_numbers):
            runner.run_agent(
                agent_config=config,
                agent_name=config["agent_type"],
                previous_agent_type=None if idx == 0 else version_numbers[idx - 1]["agent_type"],
                idx=idx,
            )

        # Verify ALL calls used initial strategy
        assert mock_process_and_generate.call_count == 3
        for call in mock_process_and_generate.call_args_list:
            params = call[0][0]
            assert params.strategy == runner.strategies["initial"], (
                f"Loop iteration {params.agent_name} should use InitialStrategy"
            )

    def test_loop_with_dependencies_uses_intermediate_strategy(self, mock_process_and_generate):
        """Loop iterations WITH dependencies should use StandardStrategy.

        This verifies downstream loop actions (loop_b depends on loop_a)
        correctly use StandardStrategy to read source_guid from upstream.
        """
        runner = AgentRunner.__new__(AgentRunner)
        runner.process_and_generate_for_agent = mock_process_and_generate
        runner.strategies = {
            "initial": MagicMock(name="InitialStrategy"),
            "intermediate": MagicMock(name="StandardStrategy"),
        }

        # Simulate loop_b iterations that depend on loop_a
        downstream_version_numbers = [
            {
                "agent_type": "loop_b_1",
                "is_versioned_agent": True,
                "version_base_name": "loop_b",
                "dependencies": ["loop_a"],  # Has dependencies!
            },
            {
                "agent_type": "loop_b_2",
                "is_versioned_agent": True,
                "version_base_name": "loop_b",
                "dependencies": ["loop_a"],
            },
        ]

        for idx, config in enumerate(downstream_version_numbers):
            runner.run_agent(
                agent_config=config,
                agent_name=config["agent_type"],
                previous_agent_type="loop_a_2" if idx > 0 else "loop_a_1",
                idx=idx + 10,  # Non-zero indices
            )

        # Verify ALL calls used intermediate strategy
        assert mock_process_and_generate.call_count == 2
        for call in mock_process_and_generate.call_args_list:
            params = call[0][0]
            assert params.strategy == runner.strategies["intermediate"], (
                f"Loop iteration {params.agent_name} with dependencies should use StandardStrategy"
            )
