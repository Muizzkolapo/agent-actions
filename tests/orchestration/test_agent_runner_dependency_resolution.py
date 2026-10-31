"""
Tests for _resolve_dependency_directories() in ActionRunner.

With the additive content (bus) model, all dependencies become input sources.
Records from different branches are merged by root_target_id downstream.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import DependencyError
from agent_actions.workflow.runner import ActionRunner


class TestDependencyPatterns:
    """Single, parallel, fan-in and versioned dependencies all resolve to input directories."""

    @pytest.fixture
    def agent_runner(self):
        """Create ActionRunner instance."""
        runner = ActionRunner.__new__(ActionRunner)
        runner.action_indices = {}
        runner.manifest_manager = None
        runner.storage_backend = None
        return runner

    @pytest.fixture
    def temp_folder(self):
        """Create temporary folder with target directory."""
        temp_dir = Path(tempfile.mkdtemp())
        target_dir = temp_dir / "target"
        target_dir.mkdir(parents=True)
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.mark.parametrize(
        ("dependencies", "action_name"),
        [
            pytest.param(["extract_data"], "validate_data", id="pattern1-single"),
            pytest.param(
                ["research_1", "research_2", "research_3"], "synthesize", id="pattern2-parallel-3"
            ),
            pytest.param(
                ["analyze_sentiment", "analyze_entities", "analyze_topics"],
                "generate_report",
                id="pattern3-fan-in-3",
            ),
            pytest.param(["action_a", "action_b"], "test_action", id="fan-in-2"),
            pytest.param(
                ["research_1", "research_2", "research_3", "summarize"],
                "final_report",
                id="versioned-with-fan-in-4",
            ),
            pytest.param(
                ["research_1", "research_2", "summarize"],
                "final_report",
                id="versioned-and-unversioned-3",
            ),
            pytest.param(["action_A"], "test_action", id="single-action-a"),
            pytest.param(["action_A", "action_B", "action_C"], "test_action", id="fan-in-abc"),
            pytest.param(
                ["classify_1", "classify_2", "classify_3"], "test_action", id="parallel-classify-3"
            ),
            pytest.param(["add_answer_text"], "generate_distractor_1", id="distractor-single"),
            pytest.param(
                ["validate_1", "validate_2", "validate_3"], "aggregate", id="aggregate-votes-3"
            ),
            pytest.param(
                ["get_authoring_prompt"], "write_scenario_question", id="write-scenario-single"
            ),
        ],
    )
    def test_every_dependency_is_an_input_directory(
        self, agent_runner, temp_folder, dependencies, action_name
    ):
        for dep in dependencies:
            (temp_folder / "target" / dep).mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder, dependencies, action_name
        )

        assert result == [temp_folder / "target" / dep for dep in dependencies]


class TestResolveDependencyDirectories:
    """Test _resolve_dependency_directories() method."""

    @pytest.fixture
    def agent_runner(self):
        """Create ActionRunner instance with mocked dependencies."""
        runner = ActionRunner.__new__(ActionRunner)
        runner.action_indices = {"action_A": 0, "action_B": 1, "action_C": 2}
        runner.manifest_manager = None  # No manifest manager for simple tests
        runner.storage_backend = None
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

    def test_missing_first_dependency_directory_raises_error(self, agent_runner, temp_agent_folder):
        """Test that a missing first dependency's directory raises DependencyError."""
        # action_A is listed first but doesn't exist, action_B exists
        (temp_agent_folder / "target" / "action_B").mkdir(parents=True, exist_ok=True)
        # Remove action_A if it exists from fixture
        action_a_dir = temp_agent_folder / "target" / "action_A"
        if action_a_dir.exists():
            action_a_dir.rmdir()

        dependencies = ["action_A", "action_B"]

        with pytest.raises(DependencyError) as exc_info:
            agent_runner._resolve_dependency_directories(
                temp_agent_folder, dependencies, "test_action"
            )

        assert "action_A" in str(exc_info.value)
        assert "not found" in str(exc_info.value)

    def test_empty_dependencies_returns_empty_list(self, agent_runner, temp_agent_folder):
        """Test empty dependencies returns empty list."""
        dependencies = []

        result = agent_runner._resolve_dependency_directories(
            temp_agent_folder, dependencies, "test_action"
        )

        assert result == []


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
        runner = ActionRunner.__new__(ActionRunner)
        runner.process_and_generate_for_action = mock_process_and_generate
        runner.strategies = {
            "initial": MagicMock(name="InitialStrategy"),
            "intermediate": MagicMock(name="StandardStrategy"),
        }

        # Call with idx=5 but no dependencies - should still use initial
        agent_config = {"agent_type": "test_action", "dependencies": []}
        runner.run_action(
            action_config=agent_config,
            action_name="test_action",
            previous_action_type=None,
            idx=5,  # Non-zero index
        )

        # Verify initial strategy was used
        call_args = mock_process_and_generate.call_args
        assert call_args is not None
        params = call_args[0][0]
        assert params.strategy == runner.strategies["initial"]

    def test_action_with_dependencies_uses_intermediate_strategy(self, mock_process_and_generate):
        """Actions with dependencies should use StandardStrategy."""
        runner = ActionRunner.__new__(ActionRunner)
        runner.process_and_generate_for_action = mock_process_and_generate
        runner.strategies = {
            "initial": MagicMock(name="InitialStrategy"),
            "intermediate": MagicMock(name="StandardStrategy"),
        }

        # Call with idx=0 but HAS dependencies - should use intermediate
        agent_config = {
            "agent_type": "downstream_action",
            "dependencies": ["upstream_action"],
        }
        runner.run_action(
            action_config=agent_config,
            action_name="downstream_action",
            previous_action_type="upstream_action",
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
        runner = ActionRunner.__new__(ActionRunner)
        runner.process_and_generate_for_action = mock_process_and_generate
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
            runner.run_action(
                action_config=config,
                action_name=config["agent_type"],
                previous_action_type=None if idx == 0 else version_numbers[idx - 1]["agent_type"],
                idx=idx,
            )

        # Verify ALL calls used initial strategy
        assert mock_process_and_generate.call_count == 3
        for call in mock_process_and_generate.call_args_list:
            params = call[0][0]
            assert params.strategy == runner.strategies["initial"], (
                f"Loop iteration {params.action_name} should use InitialStrategy"
            )

    def test_loop_with_dependencies_uses_intermediate_strategy(self, mock_process_and_generate):
        """Loop iterations WITH dependencies should use StandardStrategy.

        This verifies downstream loop actions (loop_b depends on loop_a)
        correctly use StandardStrategy to read source_guid from upstream.
        """
        runner = ActionRunner.__new__(ActionRunner)
        runner.process_and_generate_for_action = mock_process_and_generate
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
            runner.run_action(
                action_config=config,
                action_name=config["agent_type"],
                previous_action_type="loop_a_2" if idx > 0 else "loop_a_1",
                idx=idx + 10,  # Non-zero indices
            )

        # Verify ALL calls used intermediate strategy
        assert mock_process_and_generate.call_count == 2
        for call in mock_process_and_generate.call_args_list:
            params = call[0][0]
            assert params.strategy == runner.strategies["intermediate"], (
                f"Loop iteration {params.action_name} with dependencies should use StandardStrategy"
            )
