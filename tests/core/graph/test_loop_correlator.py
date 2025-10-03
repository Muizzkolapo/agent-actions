"""Tests for Loop Output Correlator functionality."""

import json
import tempfile
import pytest
from pathlib import Path
from typing import Dict, List, Any
from unittest.mock import MagicMock, patch

from agent_actions.core.graph.loop_correlator import LoopOutputCorrelator


class TestLoopOutputCorrelator:
    """Test suite for LoopOutputCorrelator."""

    @pytest.fixture
    def temp_agent_folder(self):
        """Create a temporary agent folder for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def correlator(self, temp_agent_folder):
        """Create a LoopOutputCorrelator instance."""
        return LoopOutputCorrelator(temp_agent_folder)

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
            "validate_quiz"
        ]

    @pytest.fixture
    def sample_agent_configs(self):
        """Provide sample agent configurations."""
        return {
            "extract_facts": {"agent_type": "extract_facts", "dependencies": []},
            "generate_scenarios": {"agent_type": "generate_scenarios", "dependencies": ["extract_facts"]},
            "generate_distractors_1": {"agent_type": "generate_distractors", "dependencies": ["generate_scenarios"]},
            "generate_distractors_2": {"agent_type": "generate_distractors", "dependencies": ["generate_scenarios"]},
            "generate_distractors_3": {"agent_type": "generate_distractors", "dependencies": ["generate_scenarios"]},
            "reconstruct_options": {
                "agent_type": "reconstruct_options",
                "dependencies": [],
                "loop_consumption_config": {
                    "source": "generate_distractors",
                    "pattern": "merge"
                }
            },
            "validate_quiz": {"agent_type": "validate_quiz", "dependencies": ["reconstruct_options"]}
        }

    def test_detect_explicit_loop_consumption(self, correlator, sample_execution_order, sample_agent_configs):
        """Test detection of explicit loop consumption."""
        consumption_map = correlator.detect_explicit_loop_consumption(
            sample_execution_order, sample_agent_configs
        )

        assert "reconstruct_options" in consumption_map
        config = consumption_map["reconstruct_options"]
        assert config["source_base_name"] == "generate_distractors"
        assert config["pattern"] == "merge"
        assert set(config["loop_agents"]) == {
            "generate_distractors_1",
            "generate_distractors_2",
            "generate_distractors_3"
        }
        assert "validate_quiz" not in consumption_map  # Doesn't have loop consumption config

    def test_detect_explicit_loop_consumption_no_consumption(self, correlator):
        """Test when no agents have loop consumption config."""
        execution_order = ["agent_a", "agent_b", "agent_c"]
        agent_configs = {
            "agent_a": {"dependencies": []},
            "agent_b": {"dependencies": ["agent_a"]},
            "agent_c": {"dependencies": ["agent_b"]}
        }

        consumption_map = correlator.detect_explicit_loop_consumption(execution_order, agent_configs)
        assert consumption_map == {}

    def test_filename_preservation(self, correlator, temp_agent_folder):
        """Test that original filenames are preserved during correlation."""
        # Setup loop output directories with specific filename
        loop_dirs = []
        test_filename = "Azure_AI_Questions.json"

        for i in range(1, 4):
            loop_dir = temp_agent_folder / "target" / f"node_{i}_generate_distractors_{i}"
            loop_dir.mkdir(parents=True)
            loop_dirs.append(loop_dir)

            # Create test data
            test_data = [{
                "source_guid": "test-guid-1",
                "loop_correlation_id": "test-corr-1",
                "target_id": "target-1",
                "content": {f"distractor_{i}": f"Wrong answer {i}"}
            }]

            with open(loop_dir / test_filename, 'w') as f:
                json.dump(test_data, f)

        # Prepare correlated input
        result_dir = correlator.prepare_correlated_input(
            "reconstruct_options",
            ["generate_distractors_1", "generate_distractors_2", "generate_distractors_3"],
            4
        )

        # Verify filename is preserved
        output_file = Path(result_dir) / test_filename
        assert output_file.exists(), f"Expected file {test_filename} not found"

        # Verify source file is also created with same name
        source_file = temp_agent_folder / "source" / test_filename
        assert source_file.exists(), f"Source file {test_filename} not created"

    def test_partial_record_handling(self, correlator, temp_agent_folder):
        """Test that records missing from some loops are still included."""
        # Setup loop directories
        loop1_dir = temp_agent_folder / "target" / "node_1_distractor_1"
        loop2_dir = temp_agent_folder / "target" / "node_2_distractor_2"
        loop3_dir = temp_agent_folder / "target" / "node_3_distractor_3"

        for dir in [loop1_dir, loop2_dir, loop3_dir]:
            dir.mkdir(parents=True)

        # Record 1: exists in all loops
        # Record 2: exists only in loops 1 and 2
        # Record 3: exists only in loop 1

        data_loop1 = [
            {"source_guid": "guid-1", "loop_correlation_id": "corr-1", "content": {"field_1": "value1"}},
            {"source_guid": "guid-2", "loop_correlation_id": "corr-2", "content": {"field_1": "value2"}},
            {"source_guid": "guid-3", "loop_correlation_id": "corr-3", "content": {"field_1": "value3"}}
        ]

        data_loop2 = [
            {"source_guid": "guid-1", "loop_correlation_id": "corr-1", "content": {"field_2": "value1"}},
            {"source_guid": "guid-2", "loop_correlation_id": "corr-2", "content": {"field_2": "value2"}}
        ]

        data_loop3 = [
            {"source_guid": "guid-1", "loop_correlation_id": "corr-1", "content": {"field_3": "value1"}}
        ]

        # Write test data
        with open(loop1_dir / "data.json", 'w') as f:
            json.dump(data_loop1, f)
        with open(loop2_dir / "data.json", 'w') as f:
            json.dump(data_loop2, f)
        with open(loop3_dir / "data.json", 'w') as f:
            json.dump(data_loop3, f)

        # Correlate
        result_dir = correlator.prepare_correlated_input(
            "consumer",
            ["distractor_1", "distractor_2", "distractor_3"],
            4
        )

        # Load and verify results
        output_file = Path(result_dir) / "data.json"
        with open(output_file, 'r') as f:
            correlated_data = json.load(f)

        # Should have all 3 records despite partial presence
        assert len(correlated_data) == 3

        # Verify record 1 (complete)
        record1 = next(r for r in correlated_data if r['source_guid'] == 'guid-1')
        assert 'field_1' in record1['content']
        assert 'field_2' in record1['content']
        assert 'field_3' in record1['content']

        # Verify record 2 (partial - missing from loop 3)
        record2 = next(r for r in correlated_data if r['source_guid'] == 'guid-2')
        assert 'field_1' in record2['content']
        assert 'field_2' in record2['content']
        assert 'field_3' not in record2['content']

        # Verify record 3 (only in loop 1)
        record3 = next(r for r in correlated_data if r['source_guid'] == 'guid-3')
        assert 'field_1' in record3['content']
        assert 'field_2' not in record3['content']
        assert 'field_3' not in record3['content']

    def test_multiple_file_correlation(self, correlator, temp_agent_folder):
        """Test correlation when loop agents produce multiple files."""
        # Setup directories
        loop1_dir = temp_agent_folder / "target" / "node_1_processor_1"
        loop2_dir = temp_agent_folder / "target" / "node_2_processor_2"
        loop1_dir.mkdir(parents=True)
        loop2_dir.mkdir(parents=True)

        # Create multiple files in each loop directory
        files = ["questions.json", "answers.json", "metadata.json"]

        for filename in files:
            # Loop 1 data
            data1 = [{
                "source_guid": f"{filename}-guid-1",
                "loop_correlation_id": f"{filename}-corr-1",
                "content": {"loop1_data": f"data_from_{filename}"}
            }]
            with open(loop1_dir / filename, 'w') as f:
                json.dump(data1, f)

            # Loop 2 data
            data2 = [{
                "source_guid": f"{filename}-guid-1",
                "loop_correlation_id": f"{filename}-corr-1",
                "content": {"loop2_data": f"data_from_{filename}"}
            }]
            with open(loop2_dir / filename, 'w') as f:
                json.dump(data2, f)

        # Correlate
        result_dir = correlator.prepare_correlated_input(
            "aggregator",
            ["processor_1", "processor_2"],
            3
        )

        # Verify all files are correlated separately
        for filename in files:
            output_file = Path(result_dir) / filename
            assert output_file.exists(), f"File {filename} not correlated"

            with open(output_file, 'r') as f:
                data = json.load(f)
                assert len(data) == 1
                assert 'loop1_data' in data[0]['content']
                assert 'loop2_data' in data[0]['content']

    def test_find_agent_index(self, correlator, temp_agent_folder):
        """Test finding agent index from directory structure."""
        # Create some target directories
        (temp_agent_folder / "target" / "node_0_extract").mkdir(parents=True)
        (temp_agent_folder / "target" / "node_5_process").mkdir(parents=True)
        (temp_agent_folder / "target" / "node_10_validate").mkdir(parents=True)

        assert correlator._find_agent_index("extract") == 0
        assert correlator._find_agent_index("process") == 5
        assert correlator._find_agent_index("validate") == 10
        assert correlator._find_agent_index("nonexistent") is None

    def test_load_agent_outputs_with_filenames(self, correlator, temp_agent_folder):
        """Test loading outputs while preserving filenames."""
        output_dir = temp_agent_folder / "output"
        output_dir.mkdir()

        # Create test files
        data1 = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
        data2 = {"id": 3, "value": "c"}

        with open(output_dir / "file1.json", 'w') as f:
            json.dump(data1, f)
        with open(output_dir / "file2.json", 'w') as f:
            json.dump(data2, f)

        outputs, filenames = correlator._load_agent_outputs_with_filenames(output_dir)

        # Check outputs have filename tags
        assert len(outputs) == 3
        assert all('_source_file' in o for o in outputs)

        # Check filenames set
        assert filenames == {"file1.json", "file2.json"}

        # Verify correct file associations
        file1_outputs = [o for o in outputs if o['_source_file'] == 'file1.json']
        assert len(file1_outputs) == 2
        file2_outputs = [o for o in outputs if o['_source_file'] == 'file2.json']
        assert len(file2_outputs) == 1

    def test_correlate_by_source_record(self, correlator):
        """Test the correlation logic for merging records."""
        loop_outputs = {
            "loop_1": [
                {"source_guid": "guid-a", "loop_correlation_id": "corr-1", "content": {"f1": "v1"}},
                {"source_guid": "guid-b", "loop_correlation_id": "corr-2", "content": {"f1": "v2"}}
            ],
            "loop_2": [
                {"source_guid": "guid-a", "loop_correlation_id": "corr-1", "content": {"f2": "v3"}},
                {"source_guid": "guid-b", "loop_correlation_id": "corr-2", "content": {"f2": "v4"}}
            ],
            "loop_3": [
                {"source_guid": "guid-a", "loop_correlation_id": "corr-1", "content": {"f3": "v5"}}
                # guid-b (corr-2) missing from loop_3
            ]
        }

        result = correlator._correlate_by_source_record(loop_outputs)

        # Should have both records
        assert len(result) == 2

        # Check guid-a (complete)
        rec_a = next(r for r in result if r['source_guid'] == 'guid-a')
        assert rec_a['content'] == {"f1": "v1", "f2": "v3", "f3": "v5"}

        # Check guid-b (partial)
        rec_b = next(r for r in result if r['source_guid'] == 'guid-b')
        assert rec_b['content'] == {"f1": "v2", "f2": "v4"}

    def test_write_correlated_data(self, correlator, temp_agent_folder):
        """Test writing correlated data and source file creation."""
        output_dir = temp_agent_folder / "target" / "node_5_consumer"
        output_dir.mkdir(parents=True)

        test_data = [
            {"source_guid": "g1", "content": {"field": "value"}},
            {"source_guid": "g2", "content": {"field": "value2"}}
        ]

        # Write with custom filename
        correlator._write_correlated_data(output_dir, test_data, "custom_output.json")

        # Check target file
        target_file = output_dir / "custom_output.json"
        assert target_file.exists()

        with open(target_file, 'r') as f:
            written_data = json.load(f)
            assert len(written_data) == 2
            assert written_data[0]['source_guid'] == 'g1'

        # Check source file creation
        source_file = temp_agent_folder / "source" / "custom_output.json"
        assert source_file.exists()

    def test_empty_loop_outputs(self, correlator, temp_agent_folder):
        """Test handling when no loop outputs exist."""
        result = correlator.prepare_correlated_input(
            "consumer",
            ["nonexistent_1", "nonexistent_2"],
            5
        )

        assert result is None

    def test_error_handling_in_correlation(self, correlator, temp_agent_folder):
        """Test error handling during correlation."""
        # Create a directory with invalid JSON
        loop_dir = temp_agent_folder / "target" / "node_1_loop_1"
        loop_dir.mkdir(parents=True)

        with open(loop_dir / "invalid.json", 'w') as f:
            f.write("not valid json {")

        # Should handle gracefully and return None or empty
        result = correlator.prepare_correlated_input(
            "consumer",
            ["loop_1"],
            2
        )

        # Should either return None or a valid directory with no data
        if result:
            output_files = list(Path(result).glob("*.json"))
            if output_files:
                with open(output_files[0], 'r') as f:
                    data = json.load(f)
                    assert data == []


class TestLoopOutputCorrelatorIntegration:
    """Integration tests with AgentWorkflow."""

    @pytest.fixture
    def mock_agent_workflow(self, tmp_path):
        """Create a mock AgentWorkflow setup."""
        from unittest.mock import MagicMock

        workflow = MagicMock()
        workflow.agent_name = "test_workflow"
        workflow.execution_order = [
            "extract",
            "loop_1",
            "loop_2",
            "loop_3",
            "consumer"
        ]
        workflow.agent_configs = {
            "extract": {"agent_type": "extract"},
            "loop_1": {"agent_type": "loop"},
            "loop_2": {"agent_type": "loop"},
            "loop_3": {"agent_type": "loop"},
            "consumer": {"agent_type": "consumer", "dependencies": ["loop"]}
        }

        # Create agent folder structure
        agent_folder = tmp_path / "agent_io"
        agent_folder.mkdir()
        workflow.agent_runner = MagicMock()
        workflow.agent_runner.get_agent_folder.return_value = str(agent_folder)

        return workflow, agent_folder

    def test_integration_with_agent_workflow(self, mock_agent_workflow):
        """Test integration with AgentWorkflow's _setup_correlation_if_needed."""
        workflow, agent_folder = mock_agent_workflow

        # Create loop correlator
        correlator = LoopOutputCorrelator(agent_folder)
        workflow.loop_correlator = correlator

        # Create loop output directories with data
        for i in range(1, 4):
            loop_dir = agent_folder / "target" / f"node_{i}_loop_{i}"
            loop_dir.mkdir(parents=True)

            data = [{
                "source_guid": "test-guid",
                "loop_correlation_id": "test-corr",
                "content": {f"field_{i}": f"value_{i}"}
            }]

            with open(loop_dir / "output.json", 'w') as f:
                json.dump(data, f)

        # Simulate correlation
        result = correlator.prepare_correlated_input(
            "consumer",
            ["loop_1", "loop_2", "loop_3"],
            4
        )

        assert result is not None
        output_file = Path(result) / "output.json"
        assert output_file.exists()

        with open(output_file, 'r') as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]['content']['field_1'] == 'value_1'
            assert data[0]['content']['field_2'] == 'value_2'
            assert data[0]['content']['field_3'] == 'value_3'


class TestLoopCorrelatorWithSequentialMode:
    """Test suite for LoopOutputCorrelator with sequential loop execution."""

    @pytest.fixture
    def temp_agent_folder(self):
        """Create a temporary agent folder for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def correlator(self, temp_agent_folder):
        """Create a LoopOutputCorrelator instance."""
        return LoopOutputCorrelator(temp_agent_folder)

    def test_sequential_loop_correlation_works(self, correlator, temp_agent_folder):
        """Test that correlator works correctly with sequential loop outputs."""
        # Create sequential loop output directories
        # Sequential loops execute 1 -> 2 -> 3, but correlation should work the same
        for i in range(1, 4):
            loop_dir = temp_agent_folder / "target" / f"node_{i}_refine_{i}"
            loop_dir.mkdir(parents=True)

            test_data = [{
                "source_guid": f"test-{i}",
                "loop_correlation_id": f"test-corr-{i}",
                "content": {
                    "iteration": i,
                    "data": f"refined_data_{i}"
                }
            }]

            with open(loop_dir / "output.json", 'w') as f:
                json.dump(test_data, f)

        # Correlate sequential loop outputs
        result_dir = correlator.prepare_correlated_input(
            "aggregate",
            ["refine_1", "refine_2", "refine_3"],
            4  # node index
        )

        assert result_dir is not None
        output_file = Path(result_dir) / "output.json"
        assert output_file.exists()

        with open(output_file, 'r') as f:
            data = json.load(f)
            # Should have 3 separate records (one per iteration)
            assert len(data) == 3

            # Verify each iteration's data is present
            iterations = {item["content"]["iteration"] for item in data}
            assert iterations == {1, 2, 3}

    def test_partial_sequential_failure_correlation(self, correlator, temp_agent_folder):
        """Test correlation when some sequential iterations fail."""
        # In sequential mode, if iteration 2 fails, iteration 3 never runs
        # So we should only have outputs from iterations 1 and 2

        # Create outputs for iterations 1 and 2 only
        for i in range(1, 3):  # Only 1 and 2
            loop_dir = temp_agent_folder / "target" / f"node_{i}_process_{i}"
            loop_dir.mkdir(parents=True)

            test_data = [{
                "source_guid": "test-guid",
                "loop_correlation_id": "test-corr",
                "content": {f"field_{i}": f"value_{i}"}
            }]

            with open(loop_dir / "result.json", 'w') as f:
                json.dump(test_data, f)

        # Iteration 3 directory doesn't exist (it never ran)
        # Correlator should handle this gracefully

        result_dir = correlator.prepare_correlated_input(
            "consumer",
            ["process_1", "process_2", "process_3"],  # Expected 3, but only 2 exist
            4
        )

        # Should still create correlation directory
        assert result_dir is not None
        output_file = Path(result_dir) / "result.json"

        if output_file.exists():
            with open(output_file, 'r') as f:
                data = json.load(f)
                # Should only have data from successful iterations
                assert len(data) <= 2
                if len(data) > 0:
                    # Should have fields from iterations 1 and 2
                    assert 'field_1' in data[0]['content'] or 'field_2' in data[0]['content']

    def test_sequential_loop_with_mixed_metadata(self, correlator, temp_agent_folder):
        """Test correlation when sequential loop agents have loop_mode metadata."""
        # Create outputs with loop_mode metadata
        for i in range(1, 4):
            loop_dir = temp_agent_folder / "target" / f"node_{i}_step_{i}"
            loop_dir.mkdir(parents=True)

            test_data = [{
                "source_guid": "test-guid",
                "loop_correlation_id": "test-corr",
                "loop_mode": "sequential",  # Metadata about execution mode
                "loop_iteration": i,
                "content": {"step": i, "result": f"step_{i}_result"}
            }]

            with open(loop_dir / "data.json", 'w') as f:
                json.dump(test_data, f)

        result_dir = correlator.prepare_correlated_input(
            "final",
            ["step_1", "step_2", "step_3"],
            4
        )

        assert result_dir is not None
        output_file = Path(result_dir) / "data.json"
        assert output_file.exists()

        with open(output_file, 'r') as f:
            data = json.load(f)
            # Should have merged all iterations
            assert len(data) == 1
            # Should have results from all steps
            assert data[0]['content']['step'] in [1, 2, 3]

    def test_sequential_vs_parallel_correlation_same_behavior(self, correlator, temp_agent_folder):
        """Test that correlation behavior is identical for sequential and parallel loops."""
        # Create two sets of loop outputs - one "sequential", one "parallel"
        # Both should correlate the same way

        # Sequential loop outputs
        for i in range(1, 3):
            loop_dir = temp_agent_folder / "target" / f"node_{i}_seq_{i}"
            loop_dir.mkdir(parents=True)

            test_data = [{
                "source_guid": "guid-1",
                "loop_correlation_id": "corr-1",
                "loop_mode": "sequential",
                "content": {f"seq_field_{i}": f"seq_value_{i}"}
            }]

            with open(loop_dir / "output.json", 'w') as f:
                json.dump(test_data, f)

        # Parallel loop outputs (different agents)
        for i in range(3, 5):
            loop_dir = temp_agent_folder / "target" / f"node_{i}_par_{i-2}"
            loop_dir.mkdir(parents=True)

            test_data = [{
                "source_guid": "guid-2",
                "loop_correlation_id": "corr-2",
                "loop_mode": "parallel",
                "content": {f"par_field_{i-2}": f"par_value_{i-2}"}
            }]

            with open(loop_dir / "output.json", 'w') as f:
                json.dump(test_data, f)

        # Correlate both
        seq_result = correlator.prepare_correlated_input(
            "seq_consumer",
            ["seq_1", "seq_2"],
            5
        )

        par_result = correlator.prepare_correlated_input(
            "par_consumer",
            ["par_1", "par_2"],
            6
        )

        # Both should succeed
        assert seq_result is not None
        assert par_result is not None

        # Both should merge data the same way
        seq_file = Path(seq_result) / "output.json"
        par_file = Path(par_result) / "output.json"

        assert seq_file.exists()
        assert par_file.exists()

        with open(seq_file, 'r') as f:
            seq_data = json.load(f)

        with open(par_file, 'r') as f:
            par_data = json.load(f)

        # Both should have merged content
        assert len(seq_data) == 1
        assert len(par_data) == 1

        # Sequential merged data should have both fields
        assert 'seq_field_1' in seq_data[0]['content']
        assert 'seq_field_2' in seq_data[0]['content']

        # Parallel merged data should have both fields
        assert 'par_field_1' in par_data[0]['content']
        assert 'par_field_2' in par_data[0]['content']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])