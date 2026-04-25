"""
Tests for _resolve_dependency_directories() in ActionRunner.

Tests the 4 dependency patterns:
1. Single - One dependency, output becomes input
2. Parallel Branches - Same base name (e.g., classify_1, classify_2), outputs merged
3. Fan-in - Different actions, first is primary, others via context
4. Aggregation - Different actions with reduce_key, all merged

Also tests:
- _is_parallel_branches() detection logic
- Context sources auto-inferred from context_scope
- primary_dependency override for fan-in
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import DependencyError
from agent_actions.prompt.context.scope_inference import (
    _get_version_branches,
    _is_parallel_branches,
    _resolve_input_sources_for_fan_in,
)
from agent_actions.workflow.runner import ActionRunner


class TestIsParallelBranches:
    """Test _is_parallel_branches() detection logic."""

    @pytest.mark.parametrize(
        "deps, expected",
        [
            # Parallel: same base name + numeric suffix
            (["classify_1", "classify_2", "classify_3"], True),
            (["research_1", "research_5", "research_10"], True),
            (["extract_raw_qa_1", "extract_raw_qa_2", "extract_raw_qa_3"], True),
            # Fan-in: different base names
            (["extract", "enrich", "validate"], False),
            (["classify_1", "validate_1", "score_1"], False),
            (["analyzer", "validator", "scorer"], False),
            (["classify_text", "classify_image"], False),
            # Edge: same numeric suffix but different bases
            (["classify_text_1", "classify_image_1"], False),
            # Edge: mixed versioned + non-versioned
            (["research_1", "research_2", "research_3", "summarize"], False),
        ],
        ids=[
            "same_base_numeric",
            "same_base_varied_suffix",
            "underscore_base_name",
            "different_bases",
            "mixed_bases_same_suffix",
            "no_numeric_suffix",
            "similar_different_bases",
            "different_bases_same_suffix",
            "mixed_versioned_non_versioned",
        ],
    )
    def test_parallel_detection(self, deps, expected):
        assert _is_parallel_branches(deps) is expected


class TestGetVersionBranches:
    """Test _get_version_branches() helper method."""

    def test_finds_matching_version_branches(self):
        """Finds all version branches matching a base name."""
        deps = ["research_1", "research_2", "summarize", "validate"]
        result = _get_version_branches("research", deps)
        assert result == ["research_1", "research_2"]

    def test_does_not_match_different_base_names(self):
        """Does not match deps with different base names even if suffix is numeric."""
        deps = ["classify_text_1", "classify_image_1"]
        # Looking for 'classify' versions - neither matches because base names differ
        result = _get_version_branches("classify", deps)
        assert result == []


class TestResolveInputSourcesForFanIn:
    """Test _resolve_input_sources_for_fan_in() shared helper.

    This helper is used by both infer_dependencies() and _resolve_dependency_directories()
    to resolve which dependencies are input sources vs context sources for fan-in patterns.
    """

    def test_base_name_primary_expands_to_all_versions(self):
        """Base name as primary_dependency expands to all matching versions."""
        deps = ["research_1", "research_2", "summarize"]
        input_sources, context_sources = _resolve_input_sources_for_fan_in(deps, "research")
        assert set(input_sources) == {"research_1", "research_2"}
        assert context_sources == ["summarize"]

    def test_invalid_primary_raises_value_error(self):
        """Invalid primary_dependency raises ValueError."""
        deps = ["action_a", "action_b"]
        with pytest.raises(ValueError) as exc_info:
            _resolve_input_sources_for_fan_in(deps, "nonexistent")
        assert "nonexistent" in str(exc_info.value)
        assert "not found" in str(exc_info.value)


class TestDependencyPatterns:
    """Test all 4 dependency patterns with clear examples."""

    @pytest.fixture
    def agent_runner(self):
        """Create ActionRunner instance."""
        runner = ActionRunner.__new__(ActionRunner)
        runner.action_indices = {}
        runner.manifest_manager = None
        runner.storage_backend = None
        runner.virtual_actions = {}
        return runner

    @pytest.fixture
    def temp_folder(self):
        """Create temporary folder with target directory."""
        temp_dir = Path(tempfile.mkdtemp())
        target_dir = temp_dir / "target"
        target_dir.mkdir(parents=True)
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_pattern_1_single_dependency(self, agent_runner, temp_folder):
        """
        Pattern 1: Single Dependency

        Config: dependencies: extract_data
        Result: Output becomes input
        """
        (temp_folder / "target" / "extract_data").mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder, ["extract_data"], {"dependencies": ["extract_data"]}, "validate_data"
        )

        assert len(result) == 1
        assert result[0].name == "extract_data"

    def test_pattern_2_parallel_branches(self, agent_runner, temp_folder):
        """
        Pattern 2: Parallel Branches

        Config:
          - name: research
            versions:
              range: [1, 3]
              mode: parallel

          - name: synthesize
            dependencies: [research_1, research_2, research_3]

        Result: All outputs merged into combined records
        """
        for i in [1, 2, 3]:
            (temp_folder / "target" / f"research_{i}").mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder,
            ["research_1", "research_2", "research_3"],
            {"dependencies": ["research_1", "research_2", "research_3"]},
            "synthesize",
        )

        # All directories returned for merging
        assert len(result) == 3
        assert {r.name for r in result} == {"research_1", "research_2", "research_3"}

    def test_pattern_3_fan_in(self, agent_runner, temp_folder):
        """
        Pattern 3: Fan-in (Multiple Different Actions)

        Config:
          - name: generate_report
            dependencies: [analyze_sentiment, analyze_entities, analyze_topics]
            context_scope:
              observe:
                - analyze_sentiment.*
                - analyze_entities.*
                - analyze_topics.*

        Result: All dependencies are input sources — records merge by root_target_id
        """
        for action in ["analyze_sentiment", "analyze_entities", "analyze_topics"]:
            (temp_folder / "target" / action).mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder,
            ["analyze_sentiment", "analyze_entities", "analyze_topics"],
            {
                "dependencies": ["analyze_sentiment", "analyze_entities", "analyze_topics"],
                "context_scope": {
                    "observe": ["analyze_sentiment.*", "analyze_entities.*", "analyze_topics.*"]
                },
            },
            "generate_report",
        )

        # All dependencies returned — bus model merges records by root_target_id
        assert len(result) == 3
        assert {r.name for r in result} == {
            "analyze_sentiment",
            "analyze_entities",
            "analyze_topics",
        }

    def test_pattern_4_aggregation(self, agent_runner, temp_folder):
        """
        Pattern 4: Aggregation

        Config:
          - name: aggregate_validations
            dependencies: [validator_grammar, validator_accuracy, validator_style]
            reduce_key: content_id

        Result: All outputs merged and grouped by reduce_key
        """
        for validator in ["validator_grammar", "validator_accuracy", "validator_style"]:
            (temp_folder / "target" / validator).mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder,
            ["validator_grammar", "validator_accuracy", "validator_style"],
            {
                "dependencies": ["validator_grammar", "validator_accuracy", "validator_style"],
                "reduce_key": "content_id",
            },
            "aggregate_validations",
        )

        # All directories returned for merging (aggregation pattern)
        assert len(result) == 3
        assert {r.name for r in result} == {
            "validator_grammar",
            "validator_accuracy",
            "validator_style",
        }

    def test_reduce_key_with_parallel_branches(self, agent_runner, temp_folder):
        """
        Edge case: reduce_key with parallel branches

        Config:
          - name: aggregate_classifications
            dependencies: [classify_1, classify_2, classify_3]
            reduce_key: content_id

        Behavior: All outputs are merged (parallel branches merge by default,
        reduce_key just adds grouping for downstream processing).

        Note: This is valid but rarely used since parallel branches already
        merge by default. The reduce_key adds grouping by content_id.
        """
        for i in range(1, 4):
            (temp_folder / "target" / f"classify_{i}").mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder,
            ["classify_1", "classify_2", "classify_3"],
            {
                "dependencies": ["classify_1", "classify_2", "classify_3"],
                "reduce_key": "content_id",
            },
            "aggregate_classifications",
        )

        # All directories returned for merging (reduce_key applies grouping)
        assert len(result) == 3
        assert {r.name for r in result} == {"classify_1", "classify_2", "classify_3"}

    def test_fan_in_primary_dependency_ignored(self, agent_runner, temp_folder):
        """primary_dependency is ignored — all deps are input sources in bus model."""
        for action in ["action_a", "action_b"]:
            (temp_folder / "target" / action).mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder,
            ["action_a", "action_b"],
            {
                "dependencies": ["action_a", "action_b"],
                "primary_dependency": "action_c",  # Ignored — not used in bus model
            },
            "test_action",
        )

        # All dependencies are input sources regardless of primary_dependency
        assert len(result) == 2
        assert {r.name for r in result} == {"action_a", "action_b"}

    def test_versioned_with_fan_in_all_input(self, agent_runner, temp_folder):
        """
        Fan-in with versioned + non-versioned: all are input sources.

        Bus model: all dependencies become input sources, merged by root_target_id.
        """
        for action in ["research_1", "research_2", "research_3", "summarize"]:
            (temp_folder / "target" / action).mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder,
            ["research_1", "research_2", "research_3", "summarize"],
            {"dependencies": ["research_1", "research_2", "research_3", "summarize"]},
            "final_report",
        )

        # All dependencies are input sources in bus model
        assert len(result) == 4
        assert {r.name for r in result} == {"research_1", "research_2", "research_3", "summarize"}

    def test_versioned_primary_base_name_all_input(self, agent_runner, temp_folder):
        """
        All dependencies are input sources regardless of primary_dependency.

        Bus model: primary_dependency is ignored at the runner level.
        """
        for action in ["research_1", "research_2", "summarize"]:
            (temp_folder / "target" / action).mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder,
            ["research_1", "research_2", "summarize"],
            {
                "dependencies": ["research_1", "research_2", "summarize"],
                "primary_dependency": "research",
            },
            "final_report",
        )

        # All dependencies are input sources
        assert len(result) == 3
        assert {r.name for r in result} == {"research_1", "research_2", "summarize"}

    def test_versioned_primary_explicit_branch_all_input(self, agent_runner, temp_folder):
        """
        All dependencies are input sources regardless of explicit primary_dependency.

        Bus model: primary_dependency is ignored at the runner level.
        """
        for action in ["research_1", "research_2", "summarize"]:
            (temp_folder / "target" / action).mkdir()

        result = agent_runner._resolve_dependency_directories(
            temp_folder,
            ["research_1", "research_2", "summarize"],
            {
                "dependencies": ["research_1", "research_2", "summarize"],
                "primary_dependency": "research_1",
            },
            "final_report",
        )

        # All dependencies are input sources
        assert len(result) == 3
        assert {r.name for r in result} == {"research_1", "research_2", "summarize"}


class TestResolveDependencyDirectories:
    """Test _resolve_dependency_directories() method."""

    @pytest.fixture
    def agent_runner(self):
        """Create ActionRunner instance with mocked dependencies."""
        runner = ActionRunner.__new__(ActionRunner)
        runner.action_indices = {"action_A": 0, "action_B": 1, "action_C": 2}
        runner.manifest_manager = None  # No manifest manager for simple tests
        runner.storage_backend = None
        runner.virtual_actions = {}
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

    def test_multiple_dependencies_fan_in_returns_all(self, agent_runner, temp_agent_folder):
        """Test fan-in pattern: all dependencies are input sources (bus model)."""
        dependencies = ["action_A", "action_B", "action_C"]
        agent_config = {"dependencies": dependencies}

        result = agent_runner._resolve_dependency_directories(
            temp_agent_folder, dependencies, agent_config, "test_action"
        )

        # Bus model: all dependencies are input sources, merged by root_target_id
        assert len(result) == 3
        assert {r.name for r in result} == {"action_A", "action_B", "action_C"}

    def test_multiple_dependencies_parallel_returns_all_directories(
        self, agent_runner, temp_agent_folder
    ):
        """Test parallel branches: multiple deps with same base name returns all."""
        # Create parallel branch directories
        for suffix in ["1", "2", "3"]:
            (temp_agent_folder / "target" / f"classify_{suffix}").mkdir(parents=True, exist_ok=True)

        dependencies = ["classify_1", "classify_2", "classify_3"]
        agent_config = {"dependencies": dependencies}

        result = agent_runner._resolve_dependency_directories(
            temp_agent_folder, dependencies, agent_config, "test_action"
        )

        # Parallel branches: all directories returned for merging
        assert len(result) == 3
        assert temp_agent_folder / "target" / "classify_1" in result
        assert temp_agent_folder / "target" / "classify_2" in result
        assert temp_agent_folder / "target" / "classify_3" in result

    def test_multiple_dependencies_with_reduce_key_returns_all(
        self, agent_runner, temp_agent_folder
    ):
        """Test aggregation pattern: reduce_key set returns all dependencies."""
        dependencies = ["action_A", "action_B", "action_C"]
        agent_config = {"dependencies": dependencies, "reduce_key": "parent_id"}

        result = agent_runner._resolve_dependency_directories(
            temp_agent_folder, dependencies, agent_config, "test_action"
        )

        # Aggregation with reduce_key: all directories returned for merging
        assert len(result) == 3
        assert temp_agent_folder / "target" / "action_A" in result
        assert temp_agent_folder / "target" / "action_B" in result
        assert temp_agent_folder / "target" / "action_C" in result

    def test_missing_primary_dependency_raises_error(self, agent_runner, temp_agent_folder):
        """Test that missing PRIMARY dependency raises DependencyError."""
        # action_A is primary but doesn't exist, action_B exists
        (temp_agent_folder / "target" / "action_B").mkdir(parents=True, exist_ok=True)
        # Remove action_A if it exists from fixture
        action_a_dir = temp_agent_folder / "target" / "action_A"
        if action_a_dir.exists():
            action_a_dir.rmdir()

        dependencies = ["action_A", "action_B"]
        agent_config = {"dependencies": dependencies}

        with pytest.raises(DependencyError) as exc_info:
            agent_runner._resolve_dependency_directories(
                temp_agent_folder, dependencies, agent_config, "test_action"
            )

        assert "action_A" in str(exc_info.value)
        assert "not found" in str(exc_info.value)

    def test_primary_dependency_ignored_all_input(self, agent_runner, temp_agent_folder):
        """Test primary_dependency is ignored — all deps are input sources in bus model."""
        dependencies = ["action_A", "action_B", "action_C"]
        agent_config = {
            "dependencies": dependencies,
            "primary_dependency": "action_B",  # Ignored in bus model
        }

        result = agent_runner._resolve_dependency_directories(
            temp_agent_folder, dependencies, agent_config, "test_action"
        )

        # Bus model: all dependencies are input sources
        assert len(result) == 3
        assert {r.name for r in result} == {"action_A", "action_B", "action_C"}

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
        """Create ActionRunner with workflow indices."""
        runner = ActionRunner.__new__(ActionRunner)
        runner.storage_backend = None
        runner.virtual_actions = {}
        runner.action_indices = {
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

        runner = ActionRunner.__new__(ActionRunner)
        runner.action_indices = {"validate_1": 0, "validate_2": 1, "validate_3": 2, "aggregate": 3}
        runner.manifest_manager = None
        runner.storage_backend = None
        runner.virtual_actions = {}

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
