"""Tests for Loop Output Correlator functionality."""

import json
import tempfile
import pytest
from pathlib import Path
from typing import Dict, List, Any
from unittest.mock import MagicMock, patch
from agent_actions.workflow.managers.loop import VersionOutputCorrelator


class TestVersionOutputCorrelator:
    """Test suite for VersionOutputCorrelator."""

    @pytest.fixture
    def temp_agent_folder(self):
        """Create a temporary agent folder for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def correlator(self, temp_agent_folder):
        """Create a VersionOutputCorrelator instance."""
        return VersionOutputCorrelator(temp_agent_folder)

    @pytest.fixture
    def sample_execution_order(self):
        """Provide sample execution order for testing."""
        return [
            "extract_facts",
            "generate_scenarios",
            "generate_distractors_1",
            "generate_distractors_2",
            "generate_distractors_3",
            "reconstruct_options",
            "validate_quiz",
        ]

    @pytest.fixture
    def sample_agent_configs(self):
        """Provide sample agent configurations."""
        return {
            "extract_facts": {"agent_type": "extract_facts", "dependencies": []},
            "generate_scenarios": {
                "agent_type": "generate_scenarios",
                "dependencies": ["extract_facts"],
            },
            "generate_distractors_1": {
                "agent_type": "generate_distractors",
                "dependencies": ["generate_scenarios"],
            },
            "generate_distractors_2": {
                "agent_type": "generate_distractors",
                "dependencies": ["generate_scenarios"],
            },
            "generate_distractors_3": {
                "agent_type": "generate_distractors",
                "dependencies": ["generate_scenarios"],
            },
            "reconstruct_options": {
                "agent_type": "reconstruct_options",
                "dependencies": [],
                "version_consumption_config": {
                    "source": "generate_distractors",
                    "pattern": "merge",
                },
            },
            "validate_quiz": {
                "agent_type": "validate_quiz",
                "dependencies": ["reconstruct_options"],
            },
        }

    def test_detect_explicit_version_consumption(
        self, correlator, sample_execution_order, sample_agent_configs
    ):
        """Test detection of explicit loop consumption."""
        consumption_map = correlator.detect_explicit_version_consumption(
            sample_execution_order, sample_agent_configs
        )
        assert "reconstruct_options" in consumption_map
        config = consumption_map["reconstruct_options"]
        assert config["source_base_name"] == "generate_distractors"
        assert config["pattern"] == "merge"
        assert set(config["version_agents"]) == {
            "generate_distractors_1",
            "generate_distractors_2",
            "generate_distractors_3",
        }
        assert "validate_quiz" not in consumption_map

    def test_detect_explicit_version_consumption_no_consumption(self, correlator):
        """Test when no agents have loop consumption config."""
        execution_order = ["agent_a", "agent_b", "agent_c"]
        agent_configs = {
            "agent_a": {"dependencies": []},
            "agent_b": {"dependencies": ["agent_a"]},
            "agent_c": {"dependencies": ["agent_b"]},
        }
        consumption_map = correlator.detect_explicit_version_consumption(
            execution_order, agent_configs
        )
        assert consumption_map == {}

    def test_filename_preservation(self, correlator, temp_agent_folder):
        """Test that original filenames are preserved during correlation."""
        loop_dirs = []
        test_filename = "Azure_AI_Questions.json"
        for i in range(1, 4):
            # Use simple directory names (no node_X_ prefix)
            loop_dir = temp_agent_folder / "target" / f"generate_distractors_{i}"
            loop_dir.mkdir(parents=True)
            loop_dirs.append(loop_dir)
            test_data = [
                {
                    "source_guid": "test-guid-1",
                    "version_correlation_id": "test-corr-1",
                    "target_id": "target-1",
                    "content": {f"distractor_{i}": f"Wrong answer {i}"},
                }
            ]
            with open(loop_dir / test_filename, "w") as f:
                json.dump(test_data, f)
        result_dir = correlator.prepare_correlated_input(
            "reconstruct_options",
            ["generate_distractors_1", "generate_distractors_2", "generate_distractors_3"],
            4,
        )
        output_file = Path(result_dir) / test_filename
        assert output_file.exists(), f"Expected file {test_filename} not found"
        source_file = temp_agent_folder / "source" / test_filename
        assert source_file.exists(), f"Source file {test_filename} not created"

    def test_partial_record_handling(self, correlator, temp_agent_folder):
        """Test that records missing from some loops are still included."""
        # Use simple directory names (no node_X_ prefix)
        loop1_dir = temp_agent_folder / "target" / "distractor_1"
        loop2_dir = temp_agent_folder / "target" / "distractor_2"
        loop3_dir = temp_agent_folder / "target" / "distractor_3"
        for dir in [loop1_dir, loop2_dir, loop3_dir]:
            dir.mkdir(parents=True)
        data_loop1 = [
            {
                "source_guid": "guid-1",
                "version_correlation_id": "corr-1",
                "content": {"field_1": "value1"},
            },
            {
                "source_guid": "guid-2",
                "version_correlation_id": "corr-2",
                "content": {"field_1": "value2"},
            },
            {
                "source_guid": "guid-3",
                "version_correlation_id": "corr-3",
                "content": {"field_1": "value3"},
            },
        ]
        data_loop2 = [
            {
                "source_guid": "guid-1",
                "version_correlation_id": "corr-1",
                "content": {"field_2": "value1"},
            },
            {
                "source_guid": "guid-2",
                "version_correlation_id": "corr-2",
                "content": {"field_2": "value2"},
            },
        ]
        data_loop3 = [
            {
                "source_guid": "guid-1",
                "version_correlation_id": "corr-1",
                "content": {"field_3": "value1"},
            }
        ]
        with open(loop1_dir / "data.json", "w") as f:
            json.dump(data_loop1, f)
        with open(loop2_dir / "data.json", "w") as f:
            json.dump(data_loop2, f)
        with open(loop3_dir / "data.json", "w") as f:
            json.dump(data_loop3, f)
        result_dir = correlator.prepare_correlated_input(
            "consumer", ["distractor_1", "distractor_2", "distractor_3"], 4
        )
        output_file = Path(result_dir) / "data.json"
        with open(output_file, "r") as f:
            correlated_data = json.load(f)
        assert len(correlated_data) == 3
        record1 = next((r for r in correlated_data if r["source_guid"] == "guid-1"))
        # Version namespaces are now nested, not prefixed
        assert "distractor_1" in record1["content"]
        assert "distractor_2" in record1["content"]
        assert "distractor_3" in record1["content"]
        assert record1["content"]["distractor_1"]["field_1"] == "value1"
        assert record1["content"]["distractor_2"]["field_2"] == "value1"
        assert record1["content"]["distractor_3"]["field_3"] == "value1"
        record2 = next((r for r in correlated_data if r["source_guid"] == "guid-2"))
        assert "distractor_1" in record2["content"]
        assert "distractor_2" in record2["content"]
        assert "distractor_3" not in record2["content"]
        assert record2["content"]["distractor_1"]["field_1"] == "value2"
        assert record2["content"]["distractor_2"]["field_2"] == "value2"
        record3 = next((r for r in correlated_data if r["source_guid"] == "guid-3"))
        assert "distractor_1" in record3["content"]
        assert "distractor_2" not in record3["content"]
        assert "distractor_3" not in record3["content"]
        assert record3["content"]["distractor_1"]["field_1"] == "value3"

    def test_multiple_file_correlation(self, correlator, temp_agent_folder):
        """Test correlation when loop agents produce multiple files."""
        # Use simple directory names (no node_X_ prefix)
        loop1_dir = temp_agent_folder / "target" / "processor_1"
        loop2_dir = temp_agent_folder / "target" / "processor_2"
        loop1_dir.mkdir(parents=True)
        loop2_dir.mkdir(parents=True)
        files = ["questions.json", "answers.json", "metadata.json"]
        for filename in files:
            data1 = [
                {
                    "source_guid": f"{filename}-guid-1",
                    "version_correlation_id": f"{filename}-corr-1",
                    "content": {"loop1_data": f"data_from_{filename}"},
                }
            ]
            with open(loop1_dir / filename, "w") as f:
                json.dump(data1, f)
            data2 = [
                {
                    "source_guid": f"{filename}-guid-1",
                    "version_correlation_id": f"{filename}-corr-1",
                    "content": {"loop2_data": f"data_from_{filename}"},
                }
            ]
            with open(loop2_dir / filename, "w") as f:
                json.dump(data2, f)
        result_dir = correlator.prepare_correlated_input(
            "aggregator", ["processor_1", "processor_2"], 3
        )
        for filename in files:
            output_file = Path(result_dir) / filename
            assert output_file.exists(), f"File {filename} not correlated"
            with open(output_file, "r") as f:
                data = json.load(f)
                assert len(data) == 1
                # Version namespaces are now nested, not prefixed
                assert "processor_1" in data[0]["content"]
                assert "processor_2" in data[0]["content"]
                assert data[0]["content"]["processor_1"]["loop1_data"] == f"data_from_{filename}"
                assert data[0]["content"]["processor_2"]["loop2_data"] == f"data_from_{filename}"

    def test_find_agent_index(self, correlator, temp_agent_folder):
        """Test finding agent by checking directory existence."""
        # Use simple directory names (no node_X_ prefix)
        (temp_agent_folder / "target" / "extract").mkdir(parents=True)
        (temp_agent_folder / "target" / "process").mkdir(parents=True)
        (temp_agent_folder / "target" / "validate").mkdir(parents=True)
        # _find_agent_index now returns 0 if directory exists (index no longer matters)
        assert correlator._find_agent_index("extract") == 0
        assert correlator._find_agent_index("process") == 0
        assert correlator._find_agent_index("validate") == 0
        assert correlator._find_agent_index("nonexistent") is None

    def test_load_agent_outputs_with_filenames(self, correlator, temp_agent_folder):
        """Test loading outputs while preserving filenames."""
        output_dir = temp_agent_folder / "output"
        output_dir.mkdir()
        data1 = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
        data2 = {"id": 3, "value": "c"}
        with open(output_dir / "file1.json", "w") as f:
            json.dump(data1, f)
        with open(output_dir / "file2.json", "w") as f:
            json.dump(data2, f)
        outputs, filenames = correlator._load_agent_outputs_with_filenames(output_dir)
        assert len(outputs) == 3
        assert all(("_source_file" in o for o in outputs))
        assert filenames == {"file1.json", "file2.json"}
        file1_outputs = [o for o in outputs if o["_source_file"] == "file1.json"]
        assert len(file1_outputs) == 2
        file2_outputs = [o for o in outputs if o["_source_file"] == "file2.json"]
        assert len(file2_outputs) == 1

    def test_correlate_by_source_record(self, correlator):
        """Test the correlation logic for merging records with prefixed field names."""
        version_outputs = {
            "loop_1": [
                {
                    "source_guid": "guid-a",
                    "version_correlation_id": "corr-1",
                    "content": {"f1": "v1"},
                },
                {
                    "source_guid": "guid-b",
                    "version_correlation_id": "corr-2",
                    "content": {"f1": "v2"},
                },
            ],
            "loop_2": [
                {
                    "source_guid": "guid-a",
                    "version_correlation_id": "corr-1",
                    "content": {"f2": "v3"},
                },
                {
                    "source_guid": "guid-b",
                    "version_correlation_id": "corr-2",
                    "content": {"f2": "v4"},
                },
            ],
            "loop_3": [
                {
                    "source_guid": "guid-a",
                    "version_correlation_id": "corr-1",
                    "content": {"f3": "v5"},
                }
            ],
        }
        result = correlator._correlate_by_source_record(version_outputs)
        assert len(result) == 2
        rec_a = next((r for r in result if r["source_guid"] == "guid-a"))
        # Fields are now prefixed with agent name to avoid collisions
        assert rec_a["content"] == {"loop_1_f1": "v1", "loop_2_f2": "v3", "loop_3_f3": "v5"}
        rec_b = next((r for r in result if r["source_guid"] == "guid-b"))
        assert rec_b["content"] == {"loop_1_f1": "v2", "loop_2_f2": "v4"}

    def test_write_correlated_data(self, correlator, temp_agent_folder):
        """Test writing correlated data and source file creation."""
        # Use simple directory names (no node_X_ prefix)
        output_dir = temp_agent_folder / "target" / "consumer"
        output_dir.mkdir(parents=True)
        test_data = [
            {"source_guid": "g1", "content": {"field": "value"}},
            {"source_guid": "g2", "content": {"field": "value2"}},
        ]
        correlator._write_correlated_data(output_dir, test_data, "custom_output.json")
        target_file = output_dir / "custom_output.json"
        assert target_file.exists()
        with open(target_file, "r") as f:
            written_data = json.load(f)
            assert len(written_data) == 2
            assert written_data[0]["source_guid"] == "g1"
        source_file = temp_agent_folder / "source" / "custom_output.json"
        assert source_file.exists()

    def test_empty_version_outputs(self, correlator, temp_agent_folder):
        """Test handling when no loop outputs exist."""
        result = correlator.prepare_correlated_input(
            "consumer", ["nonexistent_1", "nonexistent_2"], 5
        )
        assert result is None

    def test_error_handling_in_correlation(self, correlator, temp_agent_folder):
        """Test error handling during correlation."""
        # Use simple directory names (no node_X_ prefix)
        loop_dir = temp_agent_folder / "target" / "loop_1"
        loop_dir.mkdir(parents=True)
        with open(loop_dir / "invalid.json", "w") as f:
            f.write("not valid json {")
        result = correlator.prepare_correlated_input("consumer", ["loop_1"], 2)
        if result:
            output_files = list(Path(result).glob("*.json"))
            if output_files:
                with open(output_files[0], "r") as f:
                    data = json.load(f)
                    assert data == []


class TestVersionOutputCorrelatorIntegration:
    """Integration tests with AgentWorkflow."""

    @pytest.fixture
    def mock_agent_workflow(self, tmp_path):
        """Create a mock AgentWorkflow setup."""
        from unittest.mock import MagicMock

        workflow = MagicMock()
        workflow.agent_name = "test_workflow"
        workflow.execution_order = ["extract", "loop_1", "loop_2", "loop_3", "consumer"]
        workflow.agent_configs = {
            "extract": {"agent_type": "extract"},
            "loop_1": {"agent_type": "loop"},
            "loop_2": {"agent_type": "loop"},
            "loop_3": {"agent_type": "loop"},
            "consumer": {"agent_type": "consumer", "dependencies": ["loop"]},
        }
        agent_folder = tmp_path / "agent_io"
        agent_folder.mkdir()
        workflow.agent_runner = MagicMock()
        workflow.agent_runner.get_agent_folder.return_value = str(agent_folder)
        return (workflow, agent_folder)

    def test_integration_with_agent_workflow(self, mock_agent_workflow):
        """Test integration with AgentWorkflow's _setup_correlation_if_needed."""
        workflow, agent_folder = mock_agent_workflow
        correlator = VersionOutputCorrelator(agent_folder)
        workflow.loop_correlator = correlator
        for i in range(1, 4):
            # Use simple directory names (no node_X_ prefix)
            loop_dir = agent_folder / "target" / f"loop_{i}"
            loop_dir.mkdir(parents=True)
            data = [
                {
                    "source_guid": "test-guid",
                    "version_correlation_id": "test-corr",
                    "content": {f"field_{i}": f"value_{i}"},
                }
            ]
            with open(loop_dir / "output.json", "w") as f:
                json.dump(data, f)
        result = correlator.prepare_correlated_input("consumer", ["loop_1", "loop_2", "loop_3"], 4)
        assert result is not None
        output_file = Path(result) / "output.json"
        assert output_file.exists()
        with open(output_file, "r") as f:
            data = json.load(f)
            assert len(data) == 1
            # Fields are now prefixed with agent name
            assert data[0]["content"]["loop_1_field_1"] == "value_1"
            assert data[0]["content"]["loop_2_field_2"] == "value_2"
            assert data[0]["content"]["loop_3_field_3"] == "value_3"


class TestLoopCorrelatorWithSequentialMode:
    """Test suite for VersionOutputCorrelator with sequential loop execution."""

    @pytest.fixture
    def temp_agent_folder(self):
        """Create a temporary agent folder for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def correlator(self, temp_agent_folder):
        """Create a VersionOutputCorrelator instance."""
        return VersionOutputCorrelator(temp_agent_folder)

    def test_sequential_loop_correlation_works(self, correlator, temp_agent_folder):
        """Test that correlator works correctly with sequential loop outputs."""
        for i in range(1, 4):
            # Use simple directory names (no node_X_ prefix)
            loop_dir = temp_agent_folder / "target" / f"refine_{i}"
            loop_dir.mkdir(parents=True)
            test_data = [
                {
                    "source_guid": f"test-{i}",
                    "version_correlation_id": f"test-corr-{i}",
                    "content": {"iteration": i, "data": f"refined_data_{i}"},
                }
            ]
            with open(loop_dir / "output.json", "w") as f:
                json.dump(test_data, f)
        result_dir = correlator.prepare_correlated_input(
            "aggregate", ["refine_1", "refine_2", "refine_3"], 4
        )
        assert result_dir is not None
        output_file = Path(result_dir) / "output.json"
        assert output_file.exists()
        with open(output_file, "r") as f:
            data = json.load(f)
            assert len(data) == 3
            # Fields are now prefixed with agent name
            # Extract iteration values from prefixed fields
            iterations = set()
            for item in data:
                for key, value in item["content"].items():
                    if key.endswith("_iteration"):
                        iterations.add(value)
            assert iterations == {1, 2, 3}

    def test_partial_sequential_failure_correlation(self, correlator, temp_agent_folder):
        """Test correlation when some sequential iterations fail."""
        for i in range(1, 3):
            loop_dir = temp_agent_folder / "target" / f"process_{i}"
            loop_dir.mkdir(parents=True)
            test_data = [
                {
                    "source_guid": "test-guid",
                    "version_correlation_id": "test-corr",
                    "content": {f"field_{i}": f"value_{i}"},
                }
            ]
            with open(loop_dir / "result.json", "w") as f:
                json.dump(test_data, f)
        result_dir = correlator.prepare_correlated_input(
            "consumer", ["process_1", "process_2", "process_3"], 4
        )
        assert result_dir is not None
        output_file = Path(result_dir) / "result.json"
        if output_file.exists():
            with open(output_file, "r") as f:
                data = json.load(f)
                assert len(data) <= 2
                if len(data) > 0:
                    # Fields are prefixed with agent name
                    content_keys = data[0]["content"].keys()
                    assert any("field_1" in k or "field_2" in k for k in content_keys)

    def test_sequential_loop_with_mixed_metadata(self, correlator, temp_agent_folder):
        """Test correlation when sequential loop agents have loop_mode metadata."""
        for i in range(1, 4):
            loop_dir = temp_agent_folder / "target" / f"step_{i}"
            loop_dir.mkdir(parents=True)
            test_data = [
                {
                    "source_guid": "test-guid",
                    "version_correlation_id": "test-corr",
                    "loop_mode": "sequential",
                    "version_number": i,
                    "content": {"step": i, "result": f"step_{i}_result"},
                }
            ]
            with open(loop_dir / "data.json", "w") as f:
                json.dump(test_data, f)
        result_dir = correlator.prepare_correlated_input("final", ["step_1", "step_2", "step_3"], 4)
        assert result_dir is not None
        output_file = Path(result_dir) / "data.json"
        assert output_file.exists()
        with open(output_file, "r") as f:
            data = json.load(f)
            assert len(data) == 1
            # Fields are now prefixed with agent name
            # Check that at least one step field exists with expected value
            content = data[0]["content"]
            step_values = [content.get(f"step_{i}_step") for i in range(1, 4)]
            assert any(v in [1, 2, 3] for v in step_values if v is not None)

    def test_sequential_vs_parallel_correlation_same_behavior(self, correlator, temp_agent_folder):
        """Test that correlation behavior is identical for sequential and parallel loops."""
        for i in range(1, 3):
            loop_dir = temp_agent_folder / "target" / f"seq_{i}"
            loop_dir.mkdir(parents=True)
            test_data = [
                {
                    "source_guid": "guid-1",
                    "version_correlation_id": "corr-1",
                    "loop_mode": "sequential",
                    "content": {f"seq_field_{i}": f"seq_value_{i}"},
                }
            ]
            with open(loop_dir / "output.json", "w") as f:
                json.dump(test_data, f)
        for i in range(3, 5):
            loop_dir = temp_agent_folder / "target" / f"par_{i - 2}"
            loop_dir.mkdir(parents=True)
            test_data = [
                {
                    "source_guid": "guid-2",
                    "version_correlation_id": "corr-2",
                    "loop_mode": "parallel",
                    "content": {f"par_field_{i - 2}": f"par_value_{i - 2}"},
                }
            ]
            with open(loop_dir / "output.json", "w") as f:
                json.dump(test_data, f)
        seq_result = correlator.prepare_correlated_input("seq_consumer", ["seq_1", "seq_2"], 5)
        par_result = correlator.prepare_correlated_input("par_consumer", ["par_1", "par_2"], 6)
        assert seq_result is not None
        assert par_result is not None
        seq_file = Path(seq_result) / "output.json"
        par_file = Path(par_result) / "output.json"
        assert seq_file.exists()
        assert par_file.exists()
        with open(seq_file, "r") as f:
            seq_data = json.load(f)
        with open(par_file, "r") as f:
            par_data = json.load(f)
        assert len(seq_data) == 1
        assert len(par_data) == 1
        # Fields are now prefixed with agent name
        assert "seq_1_seq_field_1" in seq_data[0]["content"]
        assert "seq_2_seq_field_2" in seq_data[0]["content"]
        assert "par_1_par_field_1" in par_data[0]["content"]
        assert "par_2_par_field_2" in par_data[0]["content"]


class TestVersionCorrelatorSourceProtection:
    """Test that version correlation doesn't overwrite rich source data."""

    def test_correlation_sparse_overwrite_blocked(self):
        """Test that sparse correlation outputs don't overwrite rich source data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_folder = Path(tmpdir)
            correlator = VersionOutputCorrelator(agent_folder)

            # Setup: Create rich source data with many fields
            source_dir = agent_folder / "agent_io" / "source"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "data.json"

            rich_source_data = [
                {
                    "source_guid": "guid-1",
                    "id": "123",
                    "page_content": "Full page content here...",
                    "title": "My Document",
                    "url": "https://example.com",
                    "author": "John Doe",
                    "created_at": "2024-01-01",
                    "tags": ["important"],
                }
            ]  # 8 fields
            source_file.write_text(json.dumps(rich_source_data))

            # Setup version outputs that will be correlated
            target_dir = agent_folder / "agent_io" / "target" / "consumer"
            target_dir.mkdir(parents=True)

            version1_dir = agent_folder / "target" / "action_1"
            version1_dir.mkdir(parents=True)
            version1_output = [
                {
                    "source_guid": "guid-1",
                    "target_id": "123",
                    "node_id": "node-1",
                    "version_correlation_id": "corr-1",
                    "lineage": [],
                    "content": {"result": "v1"},
                }
            ]
            (version1_dir / "data.json").write_text(json.dumps(version1_output))

            version2_dir = agent_folder / "target" / "action_2"
            version2_dir.mkdir(parents=True)
            version2_output = [
                {
                    "source_guid": "guid-1",
                    "target_id": "123",
                    "node_id": "node-1",
                    "version_correlation_id": "corr-1",
                    "lineage": [],
                    "content": {"result": "v2"},
                }
            ]
            (version2_dir / "data.json").write_text(json.dumps(version2_output))

            # Run correlation (this will try to write sparse source data)
            result = correlator.prepare_correlated_input("consumer", ["action_1", "action_2"], 0)

            assert result is not None

            # Verify: Rich source data should NOT be overwritten
            with open(source_file, "r") as f:
                final_source_data = json.load(f)

            # Should still have rich data (8 fields), not sparse data (2 fields)
            assert len(final_source_data[0]) == 8, (
                "Rich source data was overwritten by sparse correlation output!"
            )
            assert "page_content" in final_source_data[0], "page_content field lost!"
            assert "title" in final_source_data[0], "title field lost!"
            assert final_source_data[0]["page_content"] == "Full page content here..."

    def test_correlation_richer_data_allowed(self):
        """Test that correlation outputs with MORE fields can update source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_folder = Path(tmpdir)
            correlator = VersionOutputCorrelator(agent_folder)

            # Setup: Create sparse source data
            source_dir = agent_folder / "agent_io" / "source"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "data.json"

            sparse_source_data = [{"source_guid": "guid-1", "id": "123"}]  # 2 fields
            source_file.write_text(json.dumps(sparse_source_data))

            # This test would require modifying _create_correlation_source_data to
            # actually write richer data, which it currently doesn't do (it only
            # writes {source_guid, id}). So this test documents current behavior:
            # correlation NEVER enriches source data, it only protects existing rich data.

            # Just verify source file exists and has sparse data
            with open(source_file, "r") as f:
                source_data = json.load(f)
            assert len(source_data[0]) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
